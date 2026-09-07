package storage

type Storage interface {
	Get(key string) (any, error)
	Set(key string, value any) error
	Delete(key string) error
	List() (map[string]any, error)
	Close() error
}
type Factory func(dataDir string) (Storage, error)

var registry = map[string]Factory{}

func Register(name string, f Factory) { registry[name] = f }
func GetFactory(name string) Factory { return registry[name] }
