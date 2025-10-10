import SwiftSyntax
import SwiftParser
import Foundation

final class ResourceLikeExcluder: SyntaxVisitor {
    private let filePath: String
    private(set) var locations: Set<String> = []

    private let targetTypeNames: Set<String> = [
        "LocalizedStringKey",
        "LocalizedStringResource",
        "TypeDisplayRepresentation",
        "DisplayRepresentation",
    ]

    init(viewMode: SyntaxTreeViewMode = .sourceAccurate, filePath: String) {
        self.filePath = filePath
        super.init(viewMode: viewMode)
    }

    override func visit(_ node: StringLiteralExprSyntax) -> SyntaxVisitorContinueKind {
        if isUnderTypedBinding(node)
            || isArgOfTargetInitializer(node)
            || isImplicitReturnForTypedProperty(node)
            || isInTargetDictValue(node)
            || isInTargetDictValueViaAsCast(node)      
        {
            let ln = SourceLoc.line(of: node, filePath: filePath)
            locations.insert("\(filePath):\(ln)")
            return .skipChildren
        }
        return .visitChildren
    }

    private func matchesTarget(_ typeOrName: String) -> Bool {
        let trimmed = typeOrName.replacingOccurrences(of: " ", with: "")
        let last = trimmed.split(separator: ".").last.map(String.init) ?? trimmed
        return targetTypeNames.contains(last)
    }

    private func isUnderTypedBinding(_ node: StringLiteralExprSyntax) -> Bool {
        var anc: Syntax? = node.parent
        while let a = anc {
            if let binding = a.as(PatternBindingSyntax.self) {
                if let ty = binding.typeAnnotation?.type.trimmedDescription,
                   matchesTarget(ty) { return true }
                if let dict = binding.typeAnnotation?.type.as(DictionaryTypeSyntax.self) {
                    if matchesTarget(dict.value.trimmedDescription) { return true }
                }
            }
            anc = a.parent
        }
        return false
    }

    private func isArgOfTargetInitializer(_ node: StringLiteralExprSyntax) -> Bool {
        var anc: Syntax? = node.parent
        while let a = anc {
            if let call = a.as(FunctionCallExprSyntax.self) {
                if let d = call.calledExpression.as(DeclReferenceExprSyntax.self),
                   matchesTarget(d.baseName.text) { return true }
                if let m = call.calledExpression.as(MemberAccessExprSyntax.self),
                   matchesTarget(m.declName.baseName.text) { return true }
            }
            anc = a.parent
        }
        return false
    }

    private func isImplicitReturnForTypedProperty(_ node: StringLiteralExprSyntax) -> Bool {
        var anc: Syntax? = node.parent
        var seenBinding: PatternBindingSyntax? = nil
        while let a = anc {
            if let binding = a.as(PatternBindingSyntax.self) { seenBinding = binding }
            if let varDecl = a.as(VariableDeclSyntax.self) {
                if let b = seenBinding,
                   let ty = b.typeAnnotation?.type.trimmedDescription,
                   matchesTarget(ty) { return true }
                if let b = seenBinding,
                   let dict = b.typeAnnotation?.type.as(DictionaryTypeSyntax.self),
                   matchesTarget(dict.value.trimmedDescription) { return true }
            }
            anc = a.parent
        }
        return false
    }

    private func isInTargetDictValue(_ node: StringLiteralExprSyntax) -> Bool {
        var anc: Syntax? = node.parent
        var dictElement: DictionaryElementSyntax? = nil
        while let a = anc {
            if let elem = a.as(DictionaryElementSyntax.self) {
                dictElement = elem
                break
            }
            if a.is(ClosureExprSyntax.self) || a.is(FunctionDeclSyntax.self) || a.is(InitializerDeclSyntax.self) {
                break
            }
            anc = a.parent
        }
        guard let element = dictElement else { return false }

        let nStart = node.positionAfterSkippingLeadingTrivia
        let nEnd   = node.endPositionBeforeTrailingTrivia
        let vStart = element.value.positionAfterSkippingLeadingTrivia
        let vEnd   = element.value.endPositionBeforeTrailingTrivia
        guard vStart <= nStart && nEnd <= vEnd else { return false }

        var up: Syntax? = element.parent
        while let a = up {
            if let binding = a.as(PatternBindingSyntax.self) {
                if let dict = binding.typeAnnotation?.type.as(DictionaryTypeSyntax.self) {
                    return matchesTarget(dict.value.trimmedDescription)
                }
                if let ty = binding.typeAnnotation?.type.trimmedDescription,
                   let val = ty.split(separator: ":").last.map({ String($0).trimmingCharacters(in: .whitespacesAndNewlines).trimmingCharacters(in: CharacterSet(charactersIn: "[]")) }),
                   matchesTarget(val) { return true }
            }
            up = a.parent
        }
        return false
    }

  
    private func isInTargetDictValueViaAsCast(_ node: StringLiteralExprSyntax) -> Bool {
        var anc: Syntax? = node.parent
        var sawDictElement = false
        while let a = anc {
            if a.is(DictionaryElementSyntax.self) { sawDictElement = true }
            if let asExpr = a.as(AsExprSyntax.self), sawDictElement {
                if let dict = asExpr.type.as(DictionaryTypeSyntax.self) {
                    return matchesTarget(dict.value.trimmedDescription)
                }
            }
            anc = a.parent
        }
        return false
    }
}
