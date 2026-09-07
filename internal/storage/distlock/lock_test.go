package distlock

import (
	"testing"
	"time"
)

func TestDistLock(t *testing.T) {
	l := New()
	if !l.TryLock("acc-1", time.Second) {
		t.Fatal()
	}
	if l.TryLock("acc-1", time.Second) {
		t.Fatal("should not re-lock")
	}
	l.Unlock("acc-1")
	if !l.TryLock("acc-1", time.Second) {
		t.Fatal()
	}
}
