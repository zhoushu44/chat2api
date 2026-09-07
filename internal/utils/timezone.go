package utils

import "time"

// 对等 utils/timezone.py
func ShanghaiNow() time.Time {
	loc, _ := time.LoadLocation("Asia/Shanghai")
	if loc == nil {
		loc = time.FixedZone("CST", 8*3600)
	}
	return time.Now().In(loc)
}

func OffsetMinutes(loc *time.Location) int {
	_, offset := time.Now().In(loc).Zone()
	return offset / 60
}
