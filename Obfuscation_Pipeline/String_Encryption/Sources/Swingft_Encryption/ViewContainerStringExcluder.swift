import Foundation
import SwiftSyntax

final class ViewContainerStringExcluder: SyntaxVisitor {
    private let filePath: String
    private(set) var locations: Set<String> = []

    private let containerTypeNames: Set<String> = [
        "vstack", "hstack", "zstack",
        "lazyvstack", "lazyhstack", "lazyvgrid", "lazyhgrid",
        "grid", "list", "section", "form", "group",
        "scrollview",
        "navigationstack", "navigationview",
        "tabview"
    ]

    init(viewMode: SyntaxTreeViewMode = .sourceAccurate, filePath: String) {
        self.filePath = filePath
        super.init(viewMode: viewMode)
    }

    override func visit(_ node: StringLiteralExprSyntax) -> SyntaxVisitorContinueKind {
        if isInsideViewContainerCall(node) || isInsideSomeViewContext(node) {
            let ln = SourceLoc.line(of: node, filePath: filePath)
            locations.insert("\(filePath):\(ln)")
            return .skipChildren
        }
        return .visitChildren
    }

    private func isInsideSomeViewContext(_ node: SyntaxProtocol) -> Bool {
        var anc: Syntax? = node.parent
        while let a = anc {
            if let fn = a.as(FunctionDeclSyntax.self), functionHasSomeViewReturn(fn) {
                return true
            }
            if let v = a.as(VariableDeclSyntax.self), variableHasSomeViewType(v) {
                return true
            }
            anc = a.parent
        }
        return false
    }

    private func functionHasSomeViewReturn(_ fn: FunctionDeclSyntax) -> Bool {
        guard let t = fn.signature.returnClause?.type else { return false }
        return typeIsSomeView(t)
    }

    private func variableHasSomeViewType(_ v: VariableDeclSyntax) -> Bool {
        for b in v.bindings {
            if let t = b.typeAnnotation?.type, typeIsSomeView(t) {
                return true
            }
        }
        return false
    }

    
    private func typeIsSomeView(_ type: TypeSyntax) -> Bool {
        let text = type.trimmedDescription.replacingOccurrences(of: " ", with: "").lowercased()
        guard text.hasPrefix("some") else { return false }
        let afterSome = String(text.dropFirst(4)) // "some" 이후
        let last = afterSome.split(separator: ".").last.map(String.init) ?? afterSome
        return last == "view"
    }

    private func isInsideViewContainerCall(_ node: StringLiteralExprSyntax) -> Bool {
        var anc: Syntax? = node.parent
        while let a = anc {
            if let call = a.as(FunctionCallExprSyntax.self) {
                if calleeIsViewContainer(call.calledExpression) {
                    return true
                }
            }
            anc = a.parent
        }
        return false
    }

    private func calleeIsViewContainer(_ expr: ExprSyntax) -> Bool {
        if let d = expr.as(DeclReferenceExprSyntax.self) {
            return matchesContainerName(d.baseName.text)
        }
        if let m = expr.as(MemberAccessExprSyntax.self) {
            return matchesContainerName(m.declName.baseName.text)
        }
        return false
    }

    private func matchesContainerName(_ name: String) -> Bool {
        let trimmed = name.replacingOccurrences(of: " ", with: "")
        let last = trimmed.split(separator: ".").last.map(String.init) ?? trimmed
        return containerTypeNames.contains(last.lowercased())
    }
}
