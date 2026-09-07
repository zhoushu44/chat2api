package protocol

// 对等 services/protocol/reasoning.py 推理链
type Reasoning struct {
	Steps []string `json:"steps"`
}

func NewReasoning(steps []string) *Reasoning {
	return &Reasoning{Steps: steps}
}

func (r *Reasoning) Summarize() string {
	if len(r.Steps) == 0 {
		return ""
	}
	return r.Steps[len(r.Steps)-1]
}
