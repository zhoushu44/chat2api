package protocol

// 对等 services/protocol/web_search_tool.py + openai_search.py
type WebSearchTool struct {
	Query string `json:"query"`
}

func (w *WebSearchTool) Search() (*SearchResult, error) {
	return Search(w.Query)
}
