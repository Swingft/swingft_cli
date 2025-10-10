//
//  ResultStore.swift
//  SyntaxAST
//
//  Created by 백승혜 on 7/15/25.
//

//  AST 분석 결과 저장소

class ResultStore {
    private var _results: [IdentifierInfo] = []
    private var _typealiasResults: [TypealiasInfo] = []
    private var _importResult: Set<String> = []
    
    func nodeAppend(_ item: IdentifierInfo) {
        _results.append(item)
    }
    func typealiasAppend(_ item: TypealiasInfo) {
        _typealiasResults.append(item)
    }
    func importAppend(_ item: String) {
        _importResult.insert(item)
    }
    
    func all() -> ([IdentifierInfo], [TypealiasInfo], Set<String>) {
        return (_results, _typealiasResults, _importResult)
    }
}
