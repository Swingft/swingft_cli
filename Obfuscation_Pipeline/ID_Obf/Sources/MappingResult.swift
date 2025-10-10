//
//  MappingResult.swift
//  Parse
//
//  Created by 백승혜 on 9/29/25.
//

import Foundation

struct MappingResult: Codable {
    let target: String
    let replacement: String
}

func readMappingResult(from fileURL: URL) throws -> [MappingResult] {
    let data = try Data(contentsOf: fileURL)
    let result = try JSONDecoder().decode([MappingResult].self, from: data)
    return result
}
