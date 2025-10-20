import Foundation
import ArgumentParser

// [수정] @main 속성을 완전히 제거합니다.
struct SymbolExtractor: ParsableCommand {
    static var configuration = CommandConfiguration(
        commandName: "SymbolExtractor",
        abstract: "A tool to extract symbols and their relationships from a Swift project."
    )

    @Argument(help: "Path to the Swift project directory.")
    var projectPath: String

    @Option(name: .shortAndLong, help: "Output path for the symbol_graph.json file.")
    var output: String = "symbol_graph.json"

    @Option(name: .long, help: "Path to a text file containing names to exclude (from resources/headers).")
    var externalExclusionList: String?

    func run() throws {
        print("🔍 Starting extraction from: \(projectPath)...")
        let projectURL = URL(fileURLWithPath: projectPath)

        let extractor = GraphExtractor()
        try extractor.extract(from: projectURL, externalExclusionsFile: externalExclusionList)

        print("✅ Found \(extractor.symbols.count) symbols and \(extractor.edges.count) relationships.")

        // [수정] ISO8-601 오타를 ISO8601로 바로잡았습니다.
        let graph = SymbolGraph(
            metadata: Metadata(
                projectPath: projectPath,
                analyzedAt: ISO8601DateFormatter().string(from: Date())
            ),
            symbols: Array(extractor.symbols.values),
            edges: Array(extractor.edges)
        )

        let encoder = JSONEncoder()
        encoder.outputFormatting = .prettyPrinted
        let jsonData = try encoder.encode(graph)

        let outputURL = URL(fileURLWithPath: output)
        try jsonData.write(to: outputURL)

        print("🎉 Successfully exported symbol graph to: \(outputURL.path)")
    }
}

// [수정] 파일 맨 아래에 이 코드를 추가하여 프로그램을 직접 실행합니다.
// 이것이 새로운 프로그램 시작점(Entry Point)이 됩니다.
SymbolExtractor.main()