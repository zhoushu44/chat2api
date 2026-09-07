package tags

import (
	"sync"
)

type Tag struct {
	ImageID string `json:"image_id"`
	Tag     string `json:"tag"`
}

type Service struct {
	mu   sync.RWMutex
	data map[string][]string // imageID -> tags
}

func New() *Service {
	return &Service{data: make(map[string][]string)}
}

func (s *Service) Add(imageID, tag string) {
	s.mu.Lock()
	defer s.mu.Unlock()
	for _, t := range s.data[imageID] {
		if t == tag {
			return
		}
	}
	s.data[imageID] = append(s.data[imageID], tag)
}

func (s *Service) List(imageID string) []string {
	s.mu.RLock()
	defer s.mu.RUnlock()
	out := make([]string, len(s.data[imageID]))
	copy(out, s.data[imageID])
	return out
}

func (s *Service) Remove(imageID, tag string) {
	s.mu.Lock()
	defer s.mu.Unlock()
	var kept []string
	for _, t := range s.data[imageID] {
		if t != tag {
			kept = append(kept, t)
		}
	}
	s.data[imageID] = kept
}
