import SwiftSyntax

final class GlobalStringCollector: SyntaxVisitor {
    private(set) var globalStrings: [(String, String)] = []
    private var scopeDepth = 0
    private let filePath: String

    init(viewMode: SyntaxTreeViewMode = .sourceAccurate, filePath: String) {
        self.filePath = filePath
        super.init(viewMode: viewMode)
    }


    override func visit(_ node: StructDeclSyntax) -> SyntaxVisitorContinueKind {
        scopeDepth += 1
        return .visitChildren
    }
    override func visitPost(_ node: StructDeclSyntax) {
        scopeDepth -= 1
    }

    override func visit(_ node: ClassDeclSyntax) -> SyntaxVisitorContinueKind {
        scopeDepth += 1
        return .visitChildren
    }
    override func visitPost(_ node: ClassDeclSyntax) {
        scopeDepth -= 1
    }


    override func visitPost(_ node: EnumDeclSyntax) {
        scopeDepth -= 1
    }

    override func visit(_ node: FunctionDeclSyntax) -> SyntaxVisitorContinueKind {
        scopeDepth += 1
        return .visitChildren
    }
    override func visitPost(_ node: FunctionDeclSyntax) {
        scopeDepth -= 1
    }

    override func visit(_ node: ExtensionDeclSyntax) -> SyntaxVisitorContinueKind {
        scopeDepth += 1
        return .visitChildren
    }
    override func visitPost(_ node: ExtensionDeclSyntax) {
        scopeDepth -= 1
    }

    override func visit(_ node: ProtocolDeclSyntax) -> SyntaxVisitorContinueKind {
        scopeDepth += 1
        return .visitChildren
    }
    override func visitPost(_ node: ProtocolDeclSyntax) {
        scopeDepth -= 1
    }

    override func visit(_ node: ActorDeclSyntax) -> SyntaxVisitorContinueKind {
        scopeDepth += 1
        return .visitChildren
    }
    override func visitPost(_ node: ActorDeclSyntax) {
        scopeDepth -= 1
    }

    override func visit(_ node: VariableDeclSyntax) -> SyntaxVisitorContinueKind {
        guard scopeDepth == 0 else { return .skipChildren }

        for binding in node.bindings {
            if let initializer = binding.initializer?.value {
                extractStringLiterals(from: initializer)
            }
        }

        return .skipChildren
    }
    override func visit(_ node: EnumDeclSyntax) -> SyntaxVisitorContinueKind {
        scopeDepth += 1

        if node.inheritanceClause?.inheritedTypes.contains(where: {
            $0.type.trimmedDescription == "String"
        }) == true {
            for member in node.memberBlock.members {
                if let enumCase = member.decl.as(EnumCaseDeclSyntax.self) {
                    for element in enumCase.elements {
                        if let rawValue = element.rawValue?.value.as(StringLiteralExprSyntax.self) {
                            let raw = rawValue.description.trimmingCharacters(in: .whitespacesAndNewlines)
                            globalStrings.append((filePath, raw))
                        }
                    }
                }
            }
        }

        return .visitChildren
    }


    private func extractStringLiterals(from expr: ExprSyntax) {
        if let str = expr.as(StringLiteralExprSyntax.self) {
          
            let raw = str.description.trimmingCharacters(in: .whitespacesAndNewlines)
            let ln = SourceLoc.line(of: str, filePath: filePath)

            globalStrings.append(("\(filePath):\(ln)", raw))

        }
        else if let array = expr.as(ArrayExprSyntax.self) {
            for element in array.elements {
                extractStringLiterals(from: element.expression)
            }
        }
        else if let dict = expr.as(DictionaryExprSyntax.self) {
            for element in dict.content.as(DictionaryElementListSyntax.self) ?? [] {
                extractStringLiterals(from: element.key)
                extractStringLiterals(from: element.value)
            }
        }
        else if let tuple = expr.as(TupleExprSyntax.self) {
            for element in tuple.elements {
                extractStringLiterals(from: element.expression)
            }
        }
    }
}
