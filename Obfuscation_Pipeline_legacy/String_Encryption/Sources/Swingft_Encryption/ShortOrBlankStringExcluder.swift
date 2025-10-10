import Foundation
import SwiftSyntax


final class ShortOrBlankStringExcluder: SyntaxVisitor {
    private let filePath: String
    private(set) var locations: Set<String> = []

    init(viewMode: SyntaxTreeViewMode = .sourceAccurate, filePath: String) {
        self.filePath = filePath
        super.init(viewMode: viewMode)
    }

    override func visit(_ node: StringLiteralExprSyntax) -> SyntaxVisitorContinueKind {
      
        guard node.segments.count == 1,
              case .stringSegment(let seg) = node.segments.first
        else {
            return .visitChildren
        }

        let raw = seg.content.text               
        let trimmed = raw.trimmingCharacters(in: .whitespacesAndNewlines)

        
        if trimmed.isEmpty {
            record(node); return .skipChildren
        }
        
        if trimmed.count == 1 {
            record(node); return .skipChildren
        }

        return .visitChildren
    }

    private func record(_ node: some SyntaxProtocol) {
        let ln = SourceLoc.line(of: node, filePath: filePath)
        locations.insert("\(filePath):\(ln)")
    }
}
