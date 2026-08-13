package actions

import (
	"fmt"
	"path/filepath"
	"syscall"
)

type DiskUsage struct {
	Path           string  `json:"path"`
	TotalBytes     uint64  `json:"total_bytes"`
	AvailableBytes uint64  `json:"available_bytes"`
	UsedBytes      uint64  `json:"used_bytes"`
	UsedPercent    float64 `json:"used_percent"`
}

func DiskUsageForPaths(paths []string) ([]DiskUsage, error) {
	if len(paths) == 0 || len(paths) > 8 {
		return nil, fmt.Errorf("between 1 and 8 paths are required")
	}
	result := make([]DiskUsage, 0, len(paths))
	for _, path := range paths {
		if !filepath.IsAbs(path) {
			return nil, fmt.Errorf("path must be absolute")
		}
		var stat syscall.Statfs_t
		if err := syscall.Statfs(path, &stat); err != nil {
			return nil, fmt.Errorf("inspect disk usage: %w", err)
		}
		total := uint64(stat.Blocks) * uint64(stat.Bsize)
		available := uint64(stat.Bavail) * uint64(stat.Bsize)
		used := total - uint64(stat.Bfree)*uint64(stat.Bsize)
		usedPercent := 0.0
		if total > 0 {
			usedPercent = float64(used) / float64(total) * 100
		}
		result = append(result, DiskUsage{
			Path: path, TotalBytes: total, AvailableBytes: available,
			UsedBytes: used, UsedPercent: usedPercent,
		})
	}
	return result, nil
}
