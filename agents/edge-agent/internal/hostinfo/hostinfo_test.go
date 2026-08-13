package hostinfo

import "testing"

func TestCollectReturnsRealRuntimeIdentity(t *testing.T) {
	capabilities, err := Collect()
	if err != nil {
		t.Fatalf("collect failed: %v", err)
	}
	if capabilities.Hostname == "" || capabilities.OS == "" || capabilities.Arch == "" {
		t.Fatal("expected hostname, OS, and architecture")
	}
	if len(capabilities.Actions) != 1 || capabilities.Actions[0] != "system.disk_usage" {
		t.Fatal("Agent must advertise only the registered read-only disk action")
	}
}
