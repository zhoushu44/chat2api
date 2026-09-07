package image

import "sort"

// 对等 image_service.py 分页+空间管理
type ImageMeta struct {
	ID        string `json:"id"`
	CreatedAt int64  `json:"created_at"`
	Size      int64  `json:"size"`
}

func Paginate(images []ImageMeta, page, pageSize int) ([]ImageMeta, int) {
	sort.Slice(images, func(i, j int) bool { return images[i].CreatedAt > images[j].CreatedAt })
	total := len(images)
	start := (page - 1) * pageSize
	if start >= total {
		return nil, total
	}
	end := start + pageSize
	if end > total {
		end = total
	}
	return images[start:end], total
}

func TotalSize(images []ImageMeta) int64 {
	var sum int64
	for _, im := range images {
		sum += im.Size
	}
	return sum
}
