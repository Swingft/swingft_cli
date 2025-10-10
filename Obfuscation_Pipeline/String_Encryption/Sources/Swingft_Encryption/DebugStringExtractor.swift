import Foundation
import SwiftSyntax

final class DebugStringExtractor: SyntaxVisitor {
    private(set) var debugStrings: [(String, String)] = []
    private let filePath: String

    private let debugFunctions: Set<String> = [
        "print", "NSLog", "debugPrint", "assert", "fatalError",
        "error", "info", "warning", "log","debug","annotation","preconditionFailure","os_log"
    ]

    init(viewMode: SyntaxTreeViewMode = .sourceAccurate, filePath: String) {
        self.filePath = filePath
        super.init(viewMode: viewMode)
    }

    override func visit(_ node: FunctionCallExprSyntax) -> SyntaxVisitorContinueKind {
        var functionName: String? = nil

        
        if let callee = node.calledExpression.as(DeclReferenceExprSyntax.self) {
            functionName = callee.baseName.text
        }

       
        else if let member = node.calledExpression.as(MemberAccessExprSyntax.self) {
            functionName = flattenMemberAccess(member)
        }

        if let name = functionName {
            if debugFunctions.contains(where: { name.hasSuffix(".\($0)") || name == $0 }) {
                for arg in node.arguments {
                    if let str = arg.expression.as(StringLiteralExprSyntax.self) {
                        let raw = str.description.trimmingCharacters(in: .whitespacesAndNewlines)
                        let ln = SourceLoc.line(of: str, filePath: filePath)
                        debugStrings.append(("\(filePath):\(ln)", raw))
                    }

                }
            }
        }

        return .visitChildren
    }

    private func flattenMemberAccess(_ member: MemberAccessExprSyntax) -> String {
        var parts: [String] = []
        var current: ExprSyntax? = ExprSyntax(member)


        while let m = current?.as(MemberAccessExprSyntax.self) {
            parts.insert(m.declName.baseName.text, at: 0)
            current = m.base
        }

        if let id = current?.as(DeclReferenceExprSyntax.self) {
            parts.insert(id.baseName.text, at: 0)
        }

        return parts.joined(separator: ".")
    }
}
