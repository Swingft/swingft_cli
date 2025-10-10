import Foundation
import SwiftSyntax

final class IdentifierStringExtractor: SyntaxVisitor {
    private(set) var identifierStrings: [(String, String)] = []
    private let filePath: String

    init(viewMode: SyntaxTreeViewMode = .sourceAccurate, filePath: String) {
        self.filePath = filePath
        super.init(viewMode: viewMode)
    }

    override func visit(_ node: FunctionCallExprSyntax) -> SyntaxVisitorContinueKind {
        let matchLabels: Set<String> = [
            "withIdentifier",
            "reuseIdentifier",
            "accessibilityIdentifier"
        ]

        let matchCallees: Set<String> = [
            "performSegue",
            "NSClassFromString",
            "NSSelectorFromString",
            "bundleFilePath"
            
        ]

        if let calledExpr = node.calledExpression.as(DeclReferenceExprSyntax.self),
           matchCallees.contains(calledExpr.baseName.text) {
            extractStrings(from: node)
        } else if let memberExpr = node.calledExpression.as(MemberAccessExprSyntax.self),
                  matchCallees.contains(memberExpr.declName.baseName.text) {
            extractStrings(from: node)
        }
        for arg in node.arguments {
            if let label = arg.label?.text,
               matchLabels.contains(label),
               let str = arg.expression.as(StringLiteralExprSyntax.self) {
                   let raw = str.description.trimmingCharacters(in: .whitespacesAndNewlines)
                   let ln = SourceLoc.line(of: str, filePath: filePath)

                   identifierStrings.append(("\(filePath):\(ln)", raw))
               }
        }

        return .visitChildren
    }

    override func visit(_ node: MemberAccessExprSyntax) -> SyntaxVisitorContinueKind {
        let keywords = ["reuseIdentifier", "accessibilityIdentifier"]
        let name = node.declName.baseName.text

        if keywords.contains(name),
           let seqExpr = node.parent?.parent?.as(SequenceExprSyntax.self) {
            let exprs = seqExpr.elements

            if exprs.count >= 3,
               let idx = exprs.index(exprs.startIndex, offsetBy: 2, limitedBy: exprs.endIndex),
               let strExpr = exprs[idx].as(StringLiteralExprSyntax.self) {
                let raw = strExpr.description.trimmingCharacters(in: .whitespacesAndNewlines)
                identifierStrings.append((filePath, raw))
            }
        }

        return .visitChildren
    }

    private func extractStrings(from node: FunctionCallExprSyntax) {
        for arg in node.arguments {
            if let str = arg.expression.as(StringLiteralExprSyntax.self) {
                let raw = str.description.trimmingCharacters(in: .whitespacesAndNewlines)
                let ln = SourceLoc.line(of: str, filePath: filePath)

                identifierStrings.append(("\(filePath):\(ln)", raw))
            }
        }
    }
}
