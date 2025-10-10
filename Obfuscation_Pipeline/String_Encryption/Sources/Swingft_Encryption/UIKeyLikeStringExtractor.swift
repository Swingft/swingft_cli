import Foundation
import SwiftSyntax


final class UIKeyLikeStringExtractor: SyntaxVisitor {
    private let filePath: String
    private(set) var uiKeyStrings: [(String, String)] = [] 

 
    private let memberNames: Set<String> = [
        "title", "message", "navigationTitle", "subtitle", "prompt",
        "label", "header", "footer", "caption", "hint", "placeholder",
        "titile",
        "alert"
    ]

    private let argLabels: Set<String> = [
        "title", "message", "subtitle", "prompt",
        "label", "header", "footer", "caption", "hint", "placeholder", "name", "description"
    ]

    private let uiWrapperTypes: Set<String> = [
        "Text", "Image", "DisplayRepresentation", "TypeDisplayRepresentation", "LocalizedStringResource", "URL"
    ]

    init(viewMode: SyntaxTreeViewMode = .sourceAccurate, filePath: String) {
        self.filePath = filePath
        super.init(viewMode: viewMode)
    }

    override func visit(_ node: FunctionCallExprSyntax) -> SyntaxVisitorContinueKind {
        if let member = node.calledExpression.as(MemberAccessExprSyntax.self) {
            let name = member.declName.baseName.text
            if memberNames.contains(name) {
                collectStrings(in: node.arguments)
                return .visitChildren
            }
        }

  
        if node.arguments.contains(where: { arg in
            if let label = arg.label?.text { return argLabels.contains(label) }
            return false
        }) {
            collectStrings(in: node.arguments)
            return .visitChildren
        }

        
        if let callee = node.calledExpression.as(DeclReferenceExprSyntax.self),
           uiWrapperTypes.contains(callee.baseName.text) {
            collectStrings(in: node.arguments)
            return .visitChildren
        }

        return .visitChildren
    }



    private func collectStrings(in args: LabeledExprListSyntax) {
        for arg in args { extractStrings(from: arg.expression) }
    }


    private func extractStrings(from expr: ExprSyntax) {
        if let lit = expr.as(StringLiteralExprSyntax.self) {
            add(literal: lit)
            return
        }
        if let call = expr.as(FunctionCallExprSyntax.self) {
            for a in call.arguments { extractStrings(from: a.expression) }
            return
        }
        if let tuple = expr.as(TupleExprSyntax.self) {
            for el in tuple.elements { extractStrings(from: el.expression) }
            return
        }
        if let array = expr.as(ArrayExprSyntax.self) {
            for el in array.elements { extractStrings(from: el.expression) }
            return
        }
        if let dict = expr.as(DictionaryExprSyntax.self),
           let list = dict.content.as(DictionaryElementListSyntax.self) {
            for el in list { extractStrings(from: el.key); extractStrings(from: el.value) }
            return
        }
    }

    private func add(literal: StringLiteralExprSyntax) {
        let raw = literal.description.trimmingCharacters(in: .whitespacesAndNewlines)
        let ln = SourceLoc.line(of: literal, filePath: filePath)
        uiKeyStrings.append(("\(filePath):\(ln)", raw))
    }
}
