package goatxf

import (
	"fmt"
	"strings"
)

// ErrorKind names a failure class from spec/engine-spec.md "Errors".
type ErrorKind string

const (
	ErrUnknownDirective ErrorKind = "unknown-directive"
	ErrUnknownTransform ErrorKind = "unknown-transform"
	ErrUnknownWire      ErrorKind = "unknown-wire"
	ErrBadDirective     ErrorKind = "bad-directive"
	ErrBadLocator       ErrorKind = "bad-locator"
	ErrMissingRoot      ErrorKind = "missing-root"
	ErrMalformedWire    ErrorKind = "malformed-wire"
	ErrTransformDecode  ErrorKind = "transform-decode"
	ErrTransformEncode  ErrorKind = "transform-encode"
	ErrUnknownFormat    ErrorKind = "unknown-format"
	ErrDuplicateFormat  ErrorKind = "duplicate-format"

	// Version 0.11 (ruling 5): load failures that had no kind.
	ErrUnterminatedQuote ErrorKind = "unterminated-quote"
	ErrMissingFormat     ErrorKind = "missing-format"
	ErrMissingVersion    ErrorKind = "missing-version"
	ErrMissingWire       ErrorKind = "missing-wire"
	ErrMissingModule     ErrorKind = "missing-module"

	// Load checks of spec/engine-spec.md "Version 0.4: model modules and
	// distribution". The message of these begins with the kind and a colon.
	ErrMissingDistribution   ErrorKind = "missing-distribution"
	ErrMissingSource         ErrorKind = "missing-source"
	ErrDistributionRefused   ErrorKind = "distribution-refused"
	ErrUnknownModule         ErrorKind = "unknown-module"
	ErrDistributionViolation ErrorKind = "distribution-violation"
	ErrModuleNotUsed         ErrorKind = "module-not-used"
	ErrUndeclaredKey         ErrorKind = "undeclared-key"
	ErrKeyTypeMismatch       ErrorKind = "key-type-mismatch"
	ErrDuplicateModule       ErrorKind = "duplicate-module"
	ErrDuplicateKey          ErrorKind = "duplicate-key"

	// Version 0.5: message kinds.
	ErrNoKind         ErrorKind = "no-kind"
	ErrDuplicateKind  ErrorKind = "duplicate-kind"
	ErrDuplicateField ErrorKind = "duplicate-field" // withdrawn in 0.6: no longer raised
)

// Error is every failure the engine returns: a kind, the format and the
// locator involved, and a human-readable detail.
type Error struct {
	Kind    ErrorKind
	Format  string
	Module  string // model module involved, when there is one
	Locator string
	Source  string // pack.def or module file, when the error comes from loading one
	Line    int    // line number in Source, 0 when not applicable
	Detail  string
}

// Error renders "<kind>: detail [where]", so every message begins with the
// error kind and a colon.
func (e *Error) Error() string {
	var b strings.Builder
	b.WriteString(string(e.Kind))
	b.WriteString(":")
	if e.Detail != "" {
		b.WriteString(" ")
		b.WriteString(e.Detail)
	}
	if w := e.where(); w != "" {
		b.WriteString(" [" + w[1:] + "]")
	}
	return b.String()
}

// where renders the format, module, locator and source of an error, each
// preceded by a space.
func (e *Error) where() string {
	var b strings.Builder
	if e.Format != "" {
		fmt.Fprintf(&b, " format=%s", e.Format)
	}
	if e.Module != "" {
		fmt.Fprintf(&b, " module=%s", e.Module)
	}
	if e.Locator != "" {
		fmt.Fprintf(&b, " locator=%s", e.Locator)
	}
	if e.Source != "" {
		if e.Line > 0 {
			fmt.Fprintf(&b, " at=%s:%d", e.Source, e.Line)
		} else {
			fmt.Fprintf(&b, " at=%s", e.Source)
		}
	}
	return b.String()
}

// DecodeError reports the fields a decode could not satisfy. The entity
// returned beside it has those fields absent.
type DecodeError struct {
	Format string
	Fields []*Error
}

func (e *DecodeError) Error() string {
	parts := make([]string, len(e.Fields))
	for i, f := range e.Fields {
		parts[i] = f.Error()
	}
	return fmt.Sprintf("%s: decode format=%s: %d field(s) failed: %s", ErrTransformDecode, e.Format, len(e.Fields), strings.Join(parts, "; "))
}

// Unwrap exposes the per-field errors to errors.As / errors.Is.
func (e *DecodeError) Unwrap() []error {
	out := make([]error, len(e.Fields))
	for i, f := range e.Fields {
		out[i] = f
	}
	return out
}

// IsKind reports whether err is, or wraps, an *Error of the given kind.
func IsKind(err error, kind ErrorKind) bool {
	var found bool
	walk(err, func(e *Error) {
		if e.Kind == kind {
			found = true
		}
	})
	return found
}

func walk(err error, fn func(*Error)) {
	if err == nil {
		return
	}
	if e, ok := err.(*Error); ok {
		fn(e)
	}
	switch u := err.(type) {
	case interface{ Unwrap() []error }:
		for _, c := range u.Unwrap() {
			walk(c, fn)
		}
	case interface{ Unwrap() error }:
		walk(u.Unwrap(), fn)
	}
}
