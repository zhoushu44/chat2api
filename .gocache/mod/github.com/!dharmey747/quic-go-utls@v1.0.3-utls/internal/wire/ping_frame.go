package wire

import (
	"github.com/Dharmey747/quic-go-utls/internal/protocol"
)

// A PingFrame is a PING frame
type PingFrame struct{}

func (f *PingFrame) Append(b []byte, _ protocol.Version) ([]byte, error) {
	return append(b, pingFrameType), nil
}

// Length of a written frame
func (f *PingFrame) Length(_ protocol.Version) protocol.ByteCount {
	return 1
}
