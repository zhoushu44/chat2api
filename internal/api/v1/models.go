package v1

import (
"net/http"

"github.com/gin-gonic/gin"
)

func HandleModels(c *gin.Context) {
data := []gin.H{
{"id": "gpt-image-2", "object": "model", "created": 0, "owned_by": "chatgpt2api"},
{"id": "codex-gpt-image-2", "object": "model", "created": 0, "owned_by": "chatgpt2api"},
{"id": "gpt-4o", "object": "model", "created": 0, "owned_by": "chatgpt2api"},
}
c.JSON(http.StatusOK, gin.H{"object": "list", "data": data})
}
