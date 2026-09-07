package protocol

import (
	"encoding/base64"
	"io"
)

// 对等 conversation.py 流式输出 + b64 边读边写
// 流式编码：io.Copy 边读边写，避免 2-5MB b64 JSON 整体驻留

func StreamEncodeB64(r io.Reader, w io.Writer) error {
	enc := base64.NewEncoder(base64.StdEncoding, w)
	defer enc.Close()
	_, err := io.Copy(enc, r)
	return err
}

func StreamDecodeB64(r io.Reader) ([]byte, error) {
	dec := base64.NewDecoder(base64.StdEncoding, r)
	return io.ReadAll(dec)
}
