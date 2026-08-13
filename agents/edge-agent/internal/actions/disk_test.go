package actions

import "testing"

func TestDiskUsageUsesSystemCallWithoutShell(t *testing.T) {
	result, err := DiskUsageForPaths([]string{"/"})
	if err != nil {
		t.Fatalf("disk usage failed: %v", err)
	}
	if len(result) != 1 || result[0].TotalBytes == 0 || result[0].Path != "/" {
		t.Fatalf("unexpected disk usage: %#v", result)
	}
}

func TestDiskUsageRejectsRelativePath(t *testing.T) {
	if _, err := DiskUsageForPaths([]string{"relative"}); err == nil {
		t.Fatal("expected relative path to be rejected")
	}
}
