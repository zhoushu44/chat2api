package v1

import (
	"encoding/base64"
	"io"
)

func readAll(r io.Reader) []byte {
	b, _ := io.ReadAll(r)
	return b
}

func encodeB64(b []byte) string {
	return base64.StdEncoding.EncodeToString(b)
}
