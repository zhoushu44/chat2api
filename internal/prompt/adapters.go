package prompt

// 对等 services/prompt_source_adapters.py
type SourceAdapter interface {
	Fetch() ([]*Prompt, error)
	Name() string
}

type StaticAdapter struct {
	prompts []*Prompt
}

func NewStatic(prompts []*Prompt) *StaticAdapter {
	return &StaticAdapter{prompts: prompts}
}
func (s *StaticAdapter) Fetch() ([]*Prompt, error) { return s.prompts, nil }
func (s *StaticAdapter) Name() string { return "static" }

type RemoteAdapter struct {
	URL string
}

func (r *RemoteAdapter) Fetch() ([]*Prompt, error) {
	// 桩：返回空，真实可 HTTP 拉取
	return nil, nil
}
func (r *RemoteAdapter) Name() string { return "remote" }
