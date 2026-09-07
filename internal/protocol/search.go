package protocol

// 对等 services/protocol/web_search_tool.py + openai_search.py
type SearchResult struct {
	Query   string `json:"query"`
	Answer  string `json:"answer"`
	Sources []string `json:"sources"`
}

func Search(query string) (*SearchResult, error) {
	// 桩：返回模拟搜索结果
	return &SearchResult{
		Query:   query,
		Answer:  "search result for " + query,
		Sources: []string{"https://example.com"},
	}, nil
}
