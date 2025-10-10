import Foundation
import SwiftSyntax


final class DataSourceConformanceExcluder: SyntaxVisitor {
    private let filePath: String
    private(set) var locations: Set<String> = []

    private var dataSourceDepth: Int = 0

    init(viewMode: SyntaxTreeViewMode = .sourceAccurate, filePath: String) {
        self.filePath = filePath
        super.init(viewMode: viewMode)
    }

    override func visit(_ node: ClassDeclSyntax) -> SyntaxVisitorContinueKind {
        if inheritsDataSource(node.inheritanceClause) { dataSourceDepth += 1 }
        return .visitChildren
    }

    override func visitPost(_ node: ClassDeclSyntax) {
        if inheritsDataSource(node.inheritanceClause) { dataSourceDepth -= 1 }
    }

    override func visit(_ node: StructDeclSyntax) -> SyntaxVisitorContinueKind {
        if inheritsDataSource(node.inheritanceClause) { dataSourceDepth += 1 }
        return .visitChildren
    }

    override func visitPost(_ node: StructDeclSyntax) {
        if inheritsDataSource(node.inheritanceClause) { dataSourceDepth -= 1 }
    }

    override func visit(_ node: EnumDeclSyntax) -> SyntaxVisitorContinueKind {
        if inheritsDataSource(node.inheritanceClause) { dataSourceDepth += 1 }
        return .visitChildren
    }

    override func visitPost(_ node: EnumDeclSyntax) {
        if inheritsDataSource(node.inheritanceClause) { dataSourceDepth -= 1 }
    }

    override func visit(_ node: StringLiteralExprSyntax) -> SyntaxVisitorContinueKind {
        if dataSourceDepth > 0 {
            let ln = SourceLoc.line(of: node, filePath: filePath)
            locations.insert("\(filePath):\(ln)")
            return .skipChildren
        }
        return .visitChildren
    }

    private func inheritsDataSource(_ clause: InheritanceClauseSyntax?) -> Bool {
        guard let types = clause?.inheritedTypes else { return false }
        for t in types {
            let name = t.type.trimmedDescription.replacingOccurrences(of: " ", with: "")
            if name.split(separator: ".").last?.lowercased() == "datasource" { return true }
        }
        return false
    }
}
