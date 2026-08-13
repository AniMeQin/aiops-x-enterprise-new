package hostinfo

import (
	"os"
	"runtime"
)

type Capabilities struct {
	Hostname string   `json:"hostname"`
	OS       string   `json:"os"`
	Arch     string   `json:"arch"`
	Actions  []string `json:"actions"`
}

func Collect() (Capabilities, error) {
	hostname, err := os.Hostname()
	if err != nil {
		return Capabilities{}, err
	}
	return Capabilities{
		Hostname: hostname,
		OS:       runtime.GOOS,
		Arch:     runtime.GOARCH,
		Actions:  []string{"system.disk_usage"},
	}, nil
}
