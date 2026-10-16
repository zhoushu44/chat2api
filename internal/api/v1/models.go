package v1

import (
"net/http"

"github.com/gin-gonic/gin"
)

func HandleModels(c *gin.Context) {
data := []gin.H{
{"id": "auto", "object": "model", "created": 0, "owned_by": "chatgpt2api"},
{"id": "gpt-5-6", "object": "model", "created": 0, "owned_by": "chatgpt2api"},
{"id": "gpt-5-3-mini", "object": "model", "created": 0, "owned_by": "chatgpt2api"},
{"id": "gpt-5-6-mini", "object": "model", "created": 0, "owned_by": "chatgpt2api"},
{"id": "gpt-5-6-t-mini", "object": "model", "created": 0, "owned_by": "chatgpt2api"},
{"id": "gpt-5-6-t-mini-mini", "object": "model", "created": 0, "owned_by": "chatgpt2api"},
{"id": "research", "object": "model", "created": 0, "owned_by": "chatgpt2api"},
{"id": "gpt-6", "object": "model", "created": 0, "owned_by": "chatgpt2api"},
{"id": "gpt-6-mini", "object": "model", "created": 0, "owned_by": "chatgpt2api"},
{"id": "gpt-6-t-mini", "object": "model", "created": 0, "owned_by": "chatgpt2api"},
{"id": "gpt-6-t-mini-mini", "object": "model", "created": 0, "owned_by": "chatgpt2api"},
{"id": "gpt-image-2", "object": "model", "created": 0, "owned_by": "chatgpt2api"},
{"id": "gpt-image-2.5", "object": "model", "created": 0, "owned_by": "chatgpt2api"},
}
c.JSON(http.StatusOK, gin.H{"object": "list", "data": data})
}
