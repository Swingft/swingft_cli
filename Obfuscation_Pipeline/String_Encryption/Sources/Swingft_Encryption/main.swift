import Foundation
import SwiftSyntax
import SwiftParser


struct StringLiteralRecord: Codable {
    let file: String
    let kind: String
    let line: Int
    let value: String
}

struct SwingftConfig: Codable {
    struct Sec: Codable {
        var obfuscation: [String]?
        var encryption: [String]?
    }
    var exclude: Sec?
    var include: Sec?
}




@inline(__always)
private func stripQuotes(_ s: String) -> String {
    if s.count >= 2, s.first == "\"", s.last == "\"" {
        return String(s.dropFirst().dropLast())
    }
    return s
}

typealias LocKey = String
@inline(__always) private func locKey(_ file: String, _ line: Int) -> String { "\(file):\(line)" }

private func mark(_ reasons: inout [LocKey:String], _ key: LocKey, _ why: String) {
    if reasons[key] == nil { reasons[key] = why }
}

private func isDirectory(_ url: URL) -> Bool {
    (try? url.resourceValues(forKeys: [.isDirectoryKey]).isDirectory) ?? false
}

private func collectSwiftFiles(under root: URL) -> [URL] {
    guard let en = FileManager.default.enumerator(
        at: root,
        includingPropertiesForKeys: [.isDirectoryKey],
        options: [.skipsPackageDescendants, .skipsHiddenFiles]
    ) as? FileManager.DirectoryEnumerator else { return [] }
    var result: [URL] = []
    for case let url as URL in en {
        if isDirectory(url) {
            let name = url.lastPathComponent.lowercased()
            if name == "pods" {
                en.skipDescendants()
                continue
            }
        }
        if url.pathExtension == "swift" {
               result.append(url)
           }
      
    }
    return result
}


private func loadConfig(at url: URL) -> SwingftConfig {
    let fm = FileManager.default
    guard fm.fileExists(atPath: url.path) else {
        fputs("The specified configuration file does not exist: \(url.path)\n", stderr)
        exit(1)
    }
    do {
        let data = try Data(contentsOf: url)
        let cfg = try JSONDecoder().decode(SwingftConfig.self, from: data)
        fputs("Config loaded: \(url.path)\n", stderr)
        return cfg
    } catch {
        fputs("Failed to parse config: \(url.path) (\(error))\n", stderr)
        exit(1)
    }
}




final class AllStringLiteralCollector: SyntaxVisitor {
    private let filePath: String
    private let source: String
    private(set) var records: [StringLiteralRecord] = []

    private lazy var converter: SourceLocationConverter = {
        SourceLocationConverter(fileName: filePath, tree: Parser.parse(source: source))
    }()

    init(filePath: String, source: String) {
        self.filePath = filePath
        self.source = source
        super.init(viewMode: .sourceAccurate)
    }

    private func line(of node: some SyntaxProtocol) -> Int {
        let pos = node.positionAfterSkippingLeadingTrivia
        let loc = converter.location(for: pos)
        return loc.line
    }

    override func visit(_ node: StringLiteralExprSyntax) -> SyntaxVisitorContinueKind {
        let raw = node.description.trimmingCharacters(in: .whitespacesAndNewlines)
        let ln = line(of: node)
        records.append(.init(file: filePath, kind: "STR", line: ln, value: raw))
        return .skipChildren
    }
}


func processFile(_ url: URL) -> ([StringLiteralRecord], [LocKey:String], [StringLiteralRecord]) {
    guard let src = try? String(contentsOf: url, encoding: .utf8) else { return ([], [:], []) }
    let tree = Parser.parse(source: src)

    
    let allCollector = AllStringLiteralCollector(filePath: url.path, source: src)
    allCollector.walk(tree)
    let allRecords = allCollector.records

    
    var exclusionReasons: [LocKey:String] = [:]
    var excludedLocations = Set<String>()

    
    do {
        let v = DebugStringExtractor(viewMode: .sourceAccurate, filePath: url.path)
        v.walk(tree)
        for (k, _) in v.debugStrings { excludedLocations.insert(k); mark(&exclusionReasons, k, "debug") }
    }

    
    do {
    let v = AttributeStringLineCollector(filePath: url.path, source: src)
    v.walk(tree)
    for ln in v.lines {
        let k = "\(url.path):\(ln)"
        excludedLocations.insert(k)
        mark(&exclusionReasons, k, "attribute")
     }
    }


    
    do {
        let v = EntryPointStringExtractor(viewMode: .sourceAccurate, filePath: url.path)
        v.walk(tree)
        for (k, _) in v.entryPointStrings { excludedLocations.insert(k); mark(&exclusionReasons, k, "entrypoint") }
    }

   
    do {
        let v = GlobalStringCollector(viewMode: .sourceAccurate, filePath: url.path)
        v.walk(tree)
        for (k, _) in v.globalStrings { excludedLocations.insert(k); mark(&exclusionReasons, k, "global") }
    }

    
    do {
        let v = IdentifierStringExtractor(viewMode: .sourceAccurate, filePath: url.path)
        v.walk(tree)
        for (k, _) in v.identifierStrings { excludedLocations.insert(k); mark(&exclusionReasons, k, "identifier") }
    }

    
    do {
        let v = LocalizedStringExtractor(viewMode: .sourceAccurate, filePath: url.path)
        v.walk(tree)
        for (k, _) in v.localizedStrings { excludedLocations.insert(k); mark(&exclusionReasons, k, "localized") }
    }

    
    do {
        let v = UIKeyLikeStringExtractor(viewMode: .sourceAccurate, filePath: url.path)
        v.walk(tree)
        for (k, _) in v.uiKeyStrings { excludedLocations.insert(k); mark(&exclusionReasons, k, "ui_keylike") }
    }

    
    do {
        let v = InterpolatedStringExtractor(viewMode: .sourceAccurate, filePath: url.path)
        v.walk(tree)
        for (k, _) in v.interpolatedStrings { excludedLocations.insert(k); mark(&exclusionReasons, k, "interpolated") }
    }
    do {
        let v = ImageLiteralStringExtractor(viewMode: .sourceAccurate, filePath: url.path)
        v.walk(tree)
        for k in v.locations {
            excludedLocations.insert(k)
            mark(&exclusionReasons, k, "image_literal")
        }
    }
    do {
    let v = ResourceLikeExcluder(viewMode: .sourceAccurate, filePath: url.path)
    v.walk(tree)
    for k in v.locations {
        excludedLocations.insert(k)
        mark(&exclusionReasons, k, "resource_like")
    }
    }
    
do {
    let v = ViewContainerStringExcluder(viewMode: .sourceAccurate, filePath: url.path)
    v.walk(tree)
    for k in v.locations {
        excludedLocations.insert(k)
        mark(&exclusionReasons, k, "view_container")
    }
}


do {
    let v = ShortOrBlankStringExcluder(viewMode: .sourceAccurate, filePath: url.path)
    v.walk(tree)
    for k in v.locations {
        excludedLocations.insert(k)
        mark(&exclusionReasons, k, "short_or_blank")
    }
}
    do {
        let v = DataSourceConformanceExcluder(viewMode: .sourceAccurate, filePath: url.path)
        v.walk(tree)
        for k in v.locations {
            excludedLocations.insert(k)
            mark(&exclusionReasons, k, "datasource_conformance")
        }
    }


     
   do {
    let v = EnumRawValueCaseStringExtractor(viewMode: .sourceAccurate, filePath: url.path)
    v.walk(tree)
    for k in v.locations {
        excludedLocations.insert(k)
        mark(&exclusionReasons, k, "enum_rawvalue") 
    }
}

    let filtered = allRecords.filter { rec in
        let key = "\(rec.file):\(rec.line)"
        return !excludedLocations.contains(key)
    }

    return (filtered, exclusionReasons, allRecords)
}


func main() {
    
    guard CommandLine.arguments.count == 3 else {
        fputs("Usage: swift run Swingft_Encryption <ProjectRootPath> <ConfigPath>\n", stderr)
        exit(1)
    }

    let rootURL = URL(fileURLWithPath: CommandLine.arguments[1])
    let configURL = URL(fileURLWithPath: CommandLine.arguments[2])

    
    let outputPath = URL(fileURLWithPath: FileManager.default.currentDirectoryPath)
        .appendingPathComponent("strings.json").path

    let cfg = loadConfig(at: configURL)
    let exEncSet: Set<String> = Set((cfg.exclude?.encryption ?? []).map { $0 })
    let inEncSetRaw: Set<String> = Set((cfg.include?.encryption ?? []).map { $0 })


    let conflicts = inEncSetRaw.intersection(exEncSet)
    if !conflicts.isEmpty {
        for s in conflicts.sorted() {
            fputs("[Warning] include/encryption & exclude/encryption create the same string: \"\(s)\" Processing with string encryption exclusion \n", stderr)
        }
    }
    let inEncSet = inEncSetRaw.subtracting(conflicts)

   
    var targetRecords: [StringLiteralRecord] = []
    var reasonMap: [LocKey:String] = [:]
    var allRecords: [StringLiteralRecord] = []

    for file in collectSwiftFiles(under: rootURL) {
        let (filtered, reasons, allInFile) = processFile(file)
        for (k, v) in reasons { reasonMap[k] = v }
        targetRecords.append(contentsOf: filtered)
        allRecords.append(contentsOf: allInFile)
    }

    



    let candidateValues = targetRecords.map { stripQuotes($0.value) }
    let candidateSet = Set(candidateValues)

  
    var excludedCounts: [String:Int] = [:]
    for v in candidateValues {
        if exEncSet.contains(v) {
            excludedCounts[v, default: 0] += 1
        }
    }

  
    let postExcluded: [StringLiteralRecord] = targetRecords.filter { rec in
        !exEncSet.contains(stripQuotes(rec.value))
    }

   
    let removedByConfig = excludedCounts.values.reduce(0, +)

    let unusedExclusions = exEncSet.subtracting(candidateSet)

    if exEncSet.isEmpty {
        
    } else if removedByConfig == 0 {
        let list = unusedExclusions.sorted().map { "\"\($0)\"" }.joined(separator: ", ")
        fputs("[Warning] Exclude/encryption item, but not found in the project.:\(list)\n", stderr)
    }



  
    if !inEncSet.isEmpty {
        for target in inEncSet.sorted() {
            let occurrences = allRecords.filter { stripQuotes($0.value) == target }
            if occurrences.isEmpty {
                fputs("[Warning]  Include/encryption item, but not found in the project: \"\(target)\" unable to encrypt\n", stderr)
                continue
            }

            var canEncrypt = false
            var blocked: [String:Int] = [:]
            for m in occurrences {
                let key = locKey(m.file, m.line)
                if let why = reasonMap[key] {
                    blocked[why, default: 0] += 1
                    continue
                }
                if exEncSet.contains(stripQuotes(m.value)) {
                    blocked["config_exclude", default: 0] += 1
                    continue
                }
                canEncrypt = true 
            }

            if !canEncrypt {
    
                fputs("[Warning] Include/encryption item, but encryption is a problem: \"\(target)\" unable to encrypt\n", stderr)
            }
        }
    }


    let encoder = JSONEncoder()
    encoder.outputFormatting = [.prettyPrinted, .sortedKeys]
    do {
        let data = try encoder.encode(postExcluded)
        try data.write(to: URL(fileURLWithPath: outputPath))
      
       
    } catch {
        fputs("Error writing JSON: \(error)\n", stderr)
        exit(2)
    }
}

main()
