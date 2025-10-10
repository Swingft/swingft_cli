import SwiftSyntax
import SwiftParser

final class AttributeStringLineCollector: SyntaxVisitor {
    private let filePath: String
    private let source: String
    private lazy var converter = SourceLocationConverter(fileName: filePath,
                                                         tree: Parser.parse(source: source))
    private var attrDepth = 0
    var lines = Set<Int>()

    init(filePath: String, source: String) {
        self.filePath = filePath
        self.source = source
        super.init(viewMode: .sourceAccurate)
    }

    override func visit(_ node: AttributeSyntax) -> SyntaxVisitorContinueKind {
        attrDepth += 1
        return .visitChildren
    }
    override func visitPost(_ node: AttributeSyntax) { attrDepth -= 1 }

    override func visit(_ node: StringLiteralExprSyntax) -> SyntaxVisitorContinueKind {
        guard attrDepth > 0 else { return .skipChildren } 
        let pos = node.positionAfterSkippingLeadingTrivia
        lines.insert(converter.location(for: pos).line)
        return .skipChildren
    }
}
