import Foundation

class StoryboardAnalyzer: NSObject, XMLParserDelegate {
    private var foundClasses = Set<String>()

    // [수정] 반환 타입을 Set<String>으로 변경하고, 단일 파일 대신 프로젝트 URL을 받도록 개선
    func analyze(projectURL: URL) -> Set<String> {
        var allFoundClasses = Set<String>()
        let fileManager = FileManager.default
        let enumerator = fileManager.enumerator(at: projectURL, includingPropertiesForKeys: nil, options: [.skipsHiddenFiles])

        while let fileURL = enumerator?.nextObject() as? URL {
            if ["storyboard", "xib"].contains(fileURL.pathExtension) {
                if let parser = XMLParser(contentsOf: fileURL) {
                    parser.delegate = self
                    foundClasses.removeAll()
                    parser.parse()
                    allFoundClasses.formUnion(foundClasses)
                }
            }
        }
        return allFoundClasses
    }

    func parser(_ parser: XMLParser, didStartElement elementName: String, namespaceURI: String?, qualifiedName qName: String?, attributes attributeDict: [String : String] = [:]) {
        if let customClass = attributeDict["customClass"] {
            foundClasses.insert(customClass)
        }
    }
}