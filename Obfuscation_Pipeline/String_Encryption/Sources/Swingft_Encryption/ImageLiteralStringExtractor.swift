import Foundation
import SwiftSyntax

final class ImageLiteralStringExtractor: SyntaxVisitor {
    private let filePath: String
    private(set) var locations: Set<String> = []

    init(viewMode: SyntaxTreeViewMode = .sourceAccurate, filePath: String) {
        self.filePath = filePath
        super.init(viewMode: viewMode)
    }

    override func visit(_ node: StringLiteralExprSyntax) -> SyntaxVisitorContinueKind {

        var anc: Syntax? = node.parent
        var depth = 0
        while let a = anc, depth < 8 {
            let desc = a.description
            if desc.contains("#imageLiteral(") {
                let ln = SourceLoc.line(of: node, filePath: filePath)
                locations.insert("\(filePath):\(ln)")
                break
            }
            anc = a.parent
            depth += 1
        }
        return .skipChildren
    }
}
