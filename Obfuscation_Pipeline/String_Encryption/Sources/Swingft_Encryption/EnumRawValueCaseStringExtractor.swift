import Foundation
import SwiftSyntax


final class EnumRawValueCaseStringExtractor: SyntaxVisitor {
    private enum RawKind { case none, string, int }

    private let filePath: String
    private var enumStack: [RawKind] = []

    private(set) var locations: Set<String> = []

    init(viewMode: SyntaxTreeViewMode = .sourceAccurate, filePath: String) {
        self.filePath = filePath
        super.init(viewMode: viewMode)
    }



    override func visit(_ node: EnumDeclSyntax) -> SyntaxVisitorContinueKind {
        enumStack.append(rawKind(of: node))
        return .visitChildren
    }

    override func visitPost(_ node: EnumDeclSyntax) {
        _ = enumStack.popLast()
    }

    
    override func visit(_ node: EnumCaseElementSyntax) -> SyntaxVisitorContinueKind {
        guard isInsideStringEnum else { return .visitChildren }
        if let initValue = node.rawValue,
           let str = initValue.value.as(StringLiteralExprSyntax.self) {
            let ln = SourceLoc.line(of: str, filePath: filePath)
            locations.insert("\(filePath):\(ln)")
        }
        return .visitChildren
    }

    
    override func visit(_ node: StringLiteralExprSyntax) -> SyntaxVisitorContinueKind {
        guard isInsideStringOrIntEnum else { return .skipChildren }
        let ln = SourceLoc.line(of: node, filePath: filePath)
        locations.insert("\(filePath):\(ln)")
        return .skipChildren
    }

    private var isInsideStringEnum: Bool {
        enumStack.contains { if case .string = $0 { return true } else { return false } }
    }

    private var isInsideStringOrIntEnum: Bool {
        enumStack.contains { $0 == .string || $0 == .int }
    }

    private func rawKind(of node: EnumDeclSyntax) -> RawKind {
        guard let clause = node.inheritanceClause else { return .none }
        for it in clause.inheritedTypes {
            let t = it.type.trimmedDescription.replacingOccurrences(of: " ", with: "")
            if t == "String" || t.hasSuffix(".String") { return .string }
            if t == "Int"    || t.hasSuffix(".Int")    { return .int }
        }
        return .none
    }
}
