//go:build gomock || generate

package mocks

//go:generate sh -c "go run go.uber.org/mock/mockgen -typed -build_flags=\"-tags=gomock\" -package mocks -destination short_header_sealer.go github.com/Dharmey747/quic-go-utls/internal/handshake ShortHeaderSealer"
//go:generate sh -c "go run go.uber.org/mock/mockgen -typed -build_flags=\"-tags=gomock\" -package mocks -destination short_header_opener.go github.com/Dharmey747/quic-go-utls/internal/handshake ShortHeaderOpener"
//go:generate sh -c "go run go.uber.org/mock/mockgen -typed -build_flags=\"-tags=gomock\" -package mocks -destination long_header_opener.go github.com/Dharmey747/quic-go-utls/internal/handshake LongHeaderOpener"
//go:generate sh -c "go run go.uber.org/mock/mockgen -typed -build_flags=\"-tags=gomock\" -package mocks -destination crypto_setup.go github.com/Dharmey747/quic-go-utls/internal/handshake CryptoSetup"
//go:generate sh -c "go run go.uber.org/mock/mockgen -typed -build_flags=\"-tags=gomock\" -package mocks -destination stream_flow_controller.go github.com/Dharmey747/quic-go-utls/internal/flowcontrol StreamFlowController"
//go:generate sh -c "go run go.uber.org/mock/mockgen -typed -build_flags=\"-tags=gomock\" -package mocks -destination congestion.go github.com/Dharmey747/quic-go-utls/internal/congestion SendAlgorithmWithDebugInfos"
//go:generate sh -c "go run go.uber.org/mock/mockgen -typed -build_flags=\"-tags=gomock\" -package mockackhandler -destination ackhandler/sent_packet_handler.go github.com/Dharmey747/quic-go-utls/internal/ackhandler SentPacketHandler"
//go:generate sh -c "go run go.uber.org/mock/mockgen -typed -build_flags=\"-tags=gomock\" -package mockackhandler -destination ackhandler/received_packet_handler.go github.com/Dharmey747/quic-go-utls/internal/ackhandler ReceivedPacketHandler"
