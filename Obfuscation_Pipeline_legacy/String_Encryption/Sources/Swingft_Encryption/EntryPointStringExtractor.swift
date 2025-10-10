import Foundation
import SwiftSyntax

final class EntryPointStringExtractor: SyntaxVisitor {
    private(set) var entryPointStrings: [(String, String)] = []
    private let filePath: String
    private var insideMainType = false
    private var insideMainFunction = false
    private var insideAppLaunchMethod = false

    init(viewMode: SyntaxTreeViewMode = .sourceAccurate, filePath: String) {
        self.filePath = filePath
        super.init(viewMode: viewMode)
    }

    override func visit(_ node: StructDeclSyntax) -> SyntaxVisitorContinueKind {
        if node.attributes.contains(where: { $0.as(AttributeSyntax.self)?.attributeName.trimmedDescription == "main" }) {
            insideMainType = true
        }
        return .visitChildren
    }

    override func visitPost(_ node: StructDeclSyntax) {
        if node.attributes.contains(where: { $0.as(AttributeSyntax.self)?.attributeName.trimmedDescription == "main" }) {
            insideMainType = false
        }
    }

    override func visit(_ node: ClassDeclSyntax) -> SyntaxVisitorContinueKind {
        if node.attributes.contains(where: { $0.as(AttributeSyntax.self)?.attributeName.trimmedDescription == "main" }) {
            insideMainType = true
        }
        return .visitChildren
    }

    override func visitPost(_ node: ClassDeclSyntax) {
        if node.attributes.contains(where: { $0.as(AttributeSyntax.self)?.attributeName.trimmedDescription == "main" }) {
            insideMainType = false
        }
    }


    override func visit(_ node: FunctionDeclSyntax) -> SyntaxVisitorContinueKind {
        if insideMainType, node.name.text == "main" {
            insideMainFunction = true
            return .visitChildren
        }

        if node.name.text == "application" {
            let params = node.signature.parameterClause.parameters
            if params.count >= 2 {
                let second = params[params.index(params.startIndex, offsetBy: 1)]
                if second.secondName?.text == "didFinishLaunchingWithOptions" {
                    insideAppLaunchMethod = true
                }
            }
        }

        return .visitChildren
    }

    override func visitPost(_ node: FunctionDeclSyntax) {
        if node.name.text == "application" {
            let parameters = node.signature.parameterClause.parameters
            if parameters.count >= 2 {
                let second = parameters[parameters.index(parameters.startIndex, offsetBy: 1)]
                if second.secondName?.text == "didFinishLaunchingWithOptions" {
                    insideAppLaunchMethod = false
                }
            }
        }
        if node.name.text == "main" {
            insideMainFunction = false
        }
    }


    override func visit(_ node: StringLiteralExprSyntax) -> SyntaxVisitorContinueKind {
        if insideMainFunction || insideAppLaunchMethod {
            let raw = node.description.trimmingCharacters(in: .whitespacesAndNewlines)
            let ln = SourceLoc.line(of: node, filePath: filePath)
            entryPointStrings.append(("\(filePath):\(ln)", raw))
        }
        return .skipChildren
    }
}
