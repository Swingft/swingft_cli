import Foundation
import SwiftSyntax

final class InterpolatedStringExtractor: SyntaxVisitor {
    private let filePath: String
    private(set) var interpolatedStrings: [(String, String)] = []

    init(viewMode: SyntaxTreeViewMode = .sourceAccurate, filePath: String) {
        self.filePath = filePath
        super.init(viewMode: viewMode)
    }

    override func visit(_ node: StringLiteralExprSyntax) -> SyntaxVisitorContinueKind {
        if hasInterpolation(node) {
            let raw = node.description.trimmingCharacters(in: .whitespacesAndNewlines)
            let ln = SourceLoc.line(of: node, filePath: filePath)
            interpolatedStrings.append(("\(filePath):\(ln)", raw))
        }
        return .skipChildren
    }


    private func hasInterpolation(_ node: StringLiteralExprSyntax) -> Bool {
        for seg in node.segments {
            if seg.as(ExpressionSegmentSyntax.self) != nil { return true }
        }

        let text = node.description
        if let regex = try? NSRegularExpression(pattern: "\\\\#{0,}[(]") {
            let range = NSRange(text.startIndex..<text.endIndex, in: text)
            return regex.firstMatch(in: text, range: range) != nil
        }
        return false
    }
}
