import Foundation
import SwiftSyntax
import SwiftParser

class GraphExtractor {
    private(set) var symbols = [String: SymbolNode]()
    private(set) var edges = Set<SymbolEdge>()
    private var externalExclusions = Set<String>()

    // ✅ 진짜 시스템 타입만 포함 (Foundation/UIKit/Swift 표준)
    private let knownSystemTypes: Set<String> = [
        // Swift Standard Library
        "String", "Int", "Double", "Float", "Bool", "Character",
        "Array", "Dictionary", "Set", "Optional",
        "Range", "ClosedRange", "PartialRangeFrom", "PartialRangeUpTo",
        "Sequence", "Collection", "RandomAccessCollection",
        "Error", "Result", "Never",
        "Equatable", "Hashable", "Comparable", "Codable", "Decodable", "Encodable",
        "CodingKey", "CaseIterable", "RawRepresentable",

        // Foundation
        "Date", "Data", "URL", "URLRequest", "URLSession", "URLComponents",
        "FileManager", "DateFormatter", "NumberFormatter", "Locale",
        "Calendar", "TimeZone", "Timer", "Process",
        "NSObject", "NSCoder", "NSCoding", "NSSecureCoding",
        "Notification", "NotificationCenter",
        "UserDefaults", "Bundle", "ProcessInfo", "UUID",
        "Notification.Name",

        // UIKit/AppKit
        "UIView", "UIViewController", "UINavigationController", "UITabBarController",
        "UITableView", "UITableViewCell", "UICollectionView", "UICollectionViewCell",
        "UIButton", "UILabel", "UIImageView", "UITextField", "UITextView",
        "UIScrollView", "UIStackView", "UIImage", "UIColor", "UIFont",
        "UIResponder", "UIGestureRecognizer", "UIControl",
        "UICollectionReusableView", "UICollectionViewLayout",
        "UICollectionViewFlowLayout", "UITableViewController",

        // CoreGraphics
        "CGFloat", "CGPoint", "CGSize", "CGRect", "CGAffineTransform",
        "CGColor", "CGImage", "CGContext",

        // MapKit
        "MKMapView", "MKAnnotation", "MKAnnotationView",

        // SwiftUI (기본 타입만)
        "View", "ViewModifier", "PreferenceKey", "EnvironmentKey",

        // Combine
        "Publisher", "Subscriber", "Cancellable", "AnyCancellable",
        "Subject", "PassthroughSubject", "CurrentValueSubject",

        // RxSwift/ReactiveSwift (외부지만 널리 쓰임)
        "Observable", "Reactive", "Observer"
    ]

    func extract(from projectURL: URL, externalExclusionsFile: String?) throws {
        if let path = externalExclusionsFile {
            loadExternalExclusions(from: path)
        }

        print("  - Analyzing Plist and Storyboard files...")
        let plistAnalyzer = PlistAnalyzer()
        let storyboardAnalyzer = StoryboardAnalyzer()
        let fileBasedExclusions = plistAnalyzer.analyze(projectURL: projectURL)
            .union(storyboardAnalyzer.analyze(projectURL: projectURL))
        self.externalExclusions.formUnion(fileBasedExclusions)

        print("  - Analyzing Swift source files...")
        let fileManager = FileManager.default
        let enumerator = fileManager.enumerator(
            at: projectURL,
            includingPropertiesForKeys: nil,
            options: [.skipsHiddenFiles, .skipsPackageDescendants]
        )!

        for case let fileURL as URL in enumerator where fileURL.pathExtension == "swift" {
            let sourceText = try String(contentsOf: fileURL, encoding: .utf8)
            let visitor = SymbolVisitor(sourceText: sourceText, fileURL: fileURL)
            let sourceTree = Parser.parse(source: sourceText)
            visitor.walk(sourceTree)

            for var symbol in visitor.symbols {
                if externalExclusions.contains(symbol.name) {
                    symbol.isReferencedByExternalFile = true
                }
                self.symbols[symbol.id] = symbol
            }
            visitor.edges.forEach { self.edges.insert($0) }
        }

        resolveRelationships()
    }

    private func loadExternalExclusions(from path: String) {
        print("  - Loading external exclusion list from: \(path)")
        do {
            let fileURL = URL(fileURLWithPath: path)
            let content = try String(contentsOf: fileURL, encoding: .utf8)
            let names = content.split(whereSeparator: \.isNewline).map(String.init)
            self.externalExclusions = Set(names)
            print("  - Loaded \(externalExclusions.count) external identifiers.")
        } catch {
            print("  - ⚠️ Warning: Could not load external exclusion list. \(error.localizedDescription)")
        }
    }

    private func resolveRelationships() {
        print("  - Resolving symbol references...")
        ensureSystemSymbolsExist()
        resolveNamedEdges()
        buildInheritanceAndConformanceChains()
        propagateChainsToMembers()
    }

    // ✅ 대폭 개선: 제네릭 타입명 파싱 및 시스템 타입만 필터링
    private func ensureSystemSymbolsExist() {
        var typeNamesToProcess = Set<String>()

        // 1. typeName에서 기본 타입만 추출
        for symbol in symbols.values {
            if let typeName = symbol.typeName {
                typeNamesToProcess.formUnion(extractBaseTypes(from: typeName))
            }
        }

        // 2. 상속/프로토콜에서 추출
        let inheritanceTypeNames = edges
            .filter { $0.type == .inheritsFrom || $0.type == .conformsTo }
            .compactMap { edge -> String? in
                guard edge.to.hasPrefix("TYPE:") else { return nil }
                return String(edge.to.dropFirst(5))
            }

        typeNamesToProcess.formUnion(inheritanceTypeNames)

        // 3. knownSystemTypes만 추가
        let symbolsByName = Dictionary(grouping: symbols.values, by: { $0.name })

        for typeName in typeNamesToProcess {
            let cleanName = typeName.trimmingCharacters(in: .whitespacesAndNewlines)

            // ✅ 핵심: knownSystemTypes에 있는 것만 시스템 심볼로 생성
            guard knownSystemTypes.contains(cleanName) else { continue }
            guard !cleanName.isEmpty else { continue }

            if symbolsByName[cleanName] != nil || symbols["system-\(cleanName)"] != nil {
                continue
            }

            let systemId = "system-\(cleanName)"
            symbols[systemId] = SymbolNode(
                id: systemId,
                name: cleanName,
                kind: .unknown,
                attributes: [],
                modifiers: [],
                isSystemSymbol: true
            )
        }
    }

    // ✅ 새로운 함수: 제네릭 타입에서 기본 타입만 추출
    private func extractBaseTypes(from typeName: String) -> Set<String> {
        var baseTypes = Set<String>()

        // 제네릭 꺾쇠 제거: "AnyPublisher<String, Never>" -> "AnyPublisher", "String", "Never"
        let cleanedTypeName = typeName
            .replacingOccurrences(of: "<", with: ",")
            .replacingOccurrences(of: ">", with: ",")
            .replacingOccurrences(of: "?", with: ",")
            .replacingOccurrences(of: "!", with: ",")
            .replacingOccurrences(of: "[", with: ",")
            .replacingOccurrences(of: "]", with: ",")
            .replacingOccurrences(of: "(", with: ",")
            .replacingOccurrences(of: ")", with: ",")

        let components = cleanedTypeName.split(separator: ",")

        for component in components {
            let trimmed = component
                .trimmingCharacters(in: .whitespacesAndNewlines)
                .trimmingCharacters(in: .punctuationCharacters)

            guard !trimmed.isEmpty else { continue }

            // 네임스페이스 제거: "FlipMate.Category" -> "Category"
            let finalName = trimmed.split(separator: ".").last.map(String.init) ?? trimmed

            baseTypes.insert(finalName)
        }

        return baseTypes
    }

    private func resolveNamedEdges() {
        var finalEdges = Set<SymbolEdge>()
        let symbolsByName = Dictionary(grouping: symbols.values, by: { $0.name })

        for edge in edges {
            if symbols[edge.to] != nil {
                finalEdges.insert(edge)
                continue
            }

            let name: String
            if edge.to.hasPrefix("TYPE:") {
                name = String(edge.to.dropFirst(5))
            } else if edge.to.hasPrefix("METHOD:") {
                name = String(edge.to.dropFirst(7))
            } else {
                finalEdges.insert(edge)
                continue
            }

            if let target = symbolsByName[name]?.first {
                finalEdges.insert(SymbolEdge(from: edge.from, to: target.id, type: edge.type))
            } else {
                // ✅ knownSystemTypes에 있을 때만 시스템 심볼 생성
                if knownSystemTypes.contains(name) {
                    let systemId = "system-\(name)"
                    if symbols[systemId] == nil {
                        symbols[systemId] = SymbolNode(
                            id: systemId,
                            name: name,
                            kind: .unknown,
                            attributes: [],
                            modifiers: [],
                            isSystemSymbol: true
                        )
                    }
                    finalEdges.insert(SymbolEdge(from: edge.from, to: systemId, type: edge.type))
                }
            }
        }
        self.edges = finalEdges
    }

    private func buildInheritanceAndConformanceChains() {
        var chainCache = [String: [String]]()

        func getChain(for symbolId: String) -> [String] {
            if let cached = chainCache[symbolId] {
                return cached
            }
            guard symbols[symbolId] != nil else { return [] }

            var chain = [String]()
            let parentEdges = edges.filter {
                $0.from == symbolId && ($0.type == .inheritsFrom || $0.type == .conformsTo)
            }

            for edge in parentEdges {
                guard let parentSymbol = symbols[edge.to] else { continue }
                chain.append(parentSymbol.name)
                chain.append(contentsOf: getChain(for: parentSymbol.id))
            }

            let uniqueChain = Array(NSOrderedSet(array: chain)) as! [String]
            chainCache[symbolId] = uniqueChain
            return uniqueChain
        }

        for id in symbols.keys {
            let chain = getChain(for: id)
            if !chain.isEmpty {
                symbols[id]?.typeInheritanceChain = chain
            }
        }
    }

    private func propagateChainsToMembers() {
        let parentChildEdges = edges.filter { $0.type == .contains }
        let classLikeSymbols = symbols.values.filter {
            $0.kind == .class || $0.kind == .struct
        }

        for symbol in classLikeSymbols {
            guard let chain = symbol.typeInheritanceChain else { continue }

            var queue = [symbol.id]
            var visited = Set<String>()

            while !queue.isEmpty {
                let currentId = queue.removeFirst()
                if visited.contains(currentId) { continue }
                visited.insert(currentId)

                let childrenIds = parentChildEdges.filter { $0.from == currentId }.map { $0.to }
                for childId in childrenIds {
                    if symbols[childId]?.typeInheritanceChain == nil {
                         symbols[childId]?.typeInheritanceChain = chain
                    }
                    queue.append(childId)
                }
            }
        }
    }
}