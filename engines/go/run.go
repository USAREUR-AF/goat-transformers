package goatxf

import "fmt"

// Runs of inner messages (spec/engine-spec.md, Version 0.92): a carrier is a
// message whose lines reach an `inner <format> run` line.

// RunResult is one result of DecodeRun or ConvertRun: the entity or the
// bytes of one message, or its error.
type RunResult struct {
	Entity *Entity // DecodeRun
	Bytes  []byte  // ConvertRun
	Err    error
}

// runDecode is what a decode of a run operation records at the `run` line.
type runDecode struct {
	reached bool
	// ordinary is set when the kind selected has no `run` line in its reach,
	// or the line was passed in a block that reads as absent: an error after
	// that is of an ordinary message (ruling 4).
	ordinary bool
	format   string   // the inner format
	msgs     []runMsg // the messages, in order
	before   int      // the outer failures recorded before the line
	stop     error    // the error that ended the run, nil for none
}

// runMsg is one message of a run: its own entity, and the failures its
// decode did not forgive, or the error that stopped it.
type runMsg struct {
	ent    *Entity
	failed []*Error
	stop   error
}

func (m *runMsg) err(format string) error {
	if m.stop != nil {
		return m.stop
	}
	if len(m.failed) > 0 {
		return &DecodeError{Format: format, Fields: m.failed}
	}
	return nil
}

// decodePack decodes a message of a pack; run is nil for `decode`.
func (e *Engine) decodePack(p *Pack, b []byte, run *runDecode) (*decodeState, error) {
	d := &decodeState{pack: p, ent: NewEntity(), limit: e.maxItems, eng: e, run: run}
	d.rec = d.ent.item()
	d.top = d.rec
	c, err := builtCodec(p)
	if err != nil {
		return nil, err
	}
	if err := c.decode(d, b); err != nil {
		return d, err
	}
	d.ent.Lists = d.rec.Lists
	return d, nil
}

// unforgiven are the failures among entries from to end of the decode that
// are errors. A key mapped by several lines takes its value from the earliest
// line whose locator is present and whose transform succeeds, so the failure
// of a line is an error only when no line gave its key a value, in the entity
// or the item the line was read for. A line whose transform succeeds and
// whose table has no entry is never forgiven (0.6 ruling 4, 0.7 ruling 10).
func (d *decodeState) unforgiven(from, to int) []*Error {
	var failed []*Error
	for i := from; i < to; i++ {
		if _, has := d.failedIn[i].Fields[d.failedKey[i]]; !has || d.failedHard[i] {
			failed = append(failed, d.failed[i])
		}
	}
	return failed
}

// joined is the outer entity with the keys of one message (0.92 ruling 9: the
// two share no key).
func joined(outer, msg *Entity) *Entity {
	j := &Entity{Fields: map[string]Value{}, Lists: map[string][]*Item{}, Residue: outer.Residue, Kind: outer.Kind, InnerKind: msg.Kind}
	for _, x := range []*Entity{outer, msg} {
		for k, v := range x.Fields {
			if _, has := j.Fields[k]; !has {
				j.Fields[k] = v
			}
		}
		for k, l := range x.Lists {
			if _, has := j.Lists[k]; !has {
				j.Lists[k] = l
			}
		}
	}
	return j
}

// DecodeRun decodes a message with the messages of its run (0.92): the entity
// of the outer lines, and one result per message. A message that reaches no
// `run` line gives one result, its entity.
func (e *Engine) DecodeRun(format string, b []byte) (*Entity, []RunResult, error) {
	p, err := e.Pack(format)
	if err != nil {
		return nil, nil, err
	}
	run := &runDecode{}
	d, err := e.decodePack(p, b, run)
	if err != nil {
		if p.runs && !run.ordinary {
			return nil, nil, err
		}
		return nil, []RunResult{{Err: err}}, nil
	}
	failed := d.unforgiven(0, len(d.failed))
	if !run.reached {
		r := RunResult{Entity: d.ent}
		if len(failed) > 0 {
			r.Err = &DecodeError{Format: p.Format, Fields: failed}
		}
		return d.ent, []RunResult{r}, nil
	}
	if len(failed) > 0 {
		return nil, nil, &DecodeError{Format: p.Format, Fields: failed}
	}
	if err := e.runItems(p.Format, d, run); err != nil {
		return nil, nil, err
	}
	results := []RunResult{}
	for i := range run.msgs {
		m := &run.msgs[i]
		if err := m.err(run.format); err != nil {
			results = append(results, RunResult{Err: err})
			continue
		}
		results = append(results, RunResult{Entity: joined(d.ent, m.ent)})
	}
	return d.ent, results, nil
}

// ConvertRun is ConvertRunOrdered with a context in no order of its own; nil
// means no context is given.
func (e *Engine) ConvertRun(from, to string, b []byte, context map[string]string) ([]RunResult, error) {
	return e.ConvertRunOrdered(from, to, b, orderedContext(context))
}

// ConvertRunOrdered converts every message of a run (0.92, Operations): to a
// format that is not a carrier pack one result per message, to a carrier pack
// one result with every message. The error is that of the call as a whole.
func (e *Engine) ConvertRunOrdered(from, to string, b []byte, ctx []KeyValue) ([]RunResult, error) {
	src, err := e.Pack(from)
	if err != nil {
		return nil, err
	}
	dst, err := e.Pack(to)
	if err != nil {
		return nil, err
	}
	keys, context := readContext(ctx)
	run := &runDecode{}
	d, err := e.decodePack(src, b, run)
	if err != nil {
		switch {
		case dst.runs && run.stop != nil:
			// In reading order the message's error comes first.
			return nil, run.stop
		case dst.runs || src.runs && !run.ordinary:
			return nil, err
		}
		return []RunResult{{Err: err}}, nil
	}
	if !run.reached {
		return e.convertOrdinary(d, from, dst, keys, context)
	}
	if dst.runs {
		out, err := e.convertCarrier(d, run, from, dst, keys, context)
		if err != nil {
			return nil, err
		}
		return []RunResult{{Bytes: out}}, nil
	}
	// Errors of the outer lines, then the context, are the call's (ruling 4).
	if failed := d.unforgiven(0, len(d.failed)); len(failed) > 0 {
		return nil, &DecodeError{Format: from, Fields: failed}
	}
	if err := e.runItems(from, d, run); err != nil {
		return nil, err
	}
	vals, err := e.contextValues(keys, context)
	if err != nil {
		return nil, err
	}
	results := []RunResult{}
	for i := range run.msgs {
		m := &run.msgs[i]
		if err := m.err(run.format); err != nil {
			results = append(results, RunResult{Err: err})
			continue
		}
		j := joined(d.ent, m.ent)
		keepKinds(j, from, dst)
		fillValues(j, keys, vals)
		e.Complete(j)
		if err := e.checkHeld(dst, j); err != nil {
			results = append(results, RunResult{Err: err})
			continue
		}
		out, err := e.Encode(to, j)
		results = append(results, RunResult{Bytes: out, Err: err})
	}
	return results, nil
}

// convertOrdinary converts a message that reaches no `run` line: one result,
// or to a carrier pack the call's error (0.92 ruling 4).
func (e *Engine) convertOrdinary(d *decodeState, from string, dst *Pack, keys []string, context map[string]string) ([]RunResult, error) {
	result := func(out []byte, err error) ([]RunResult, error) {
		if err != nil && dst.runs {
			return nil, err
		}
		return []RunResult{{Bytes: out, Err: err}}, nil
	}
	if failed := d.unforgiven(0, len(d.failed)); len(failed) > 0 {
		return result(nil, &DecodeError{Format: from, Fields: failed})
	}
	vals, err := e.contextValues(keys, context)
	if err != nil {
		return nil, err
	}
	keepKinds(d.ent, from, dst)
	if from != dst.Format || context != nil {
		fillValues(d.ent, keys, vals)
		e.Complete(d.ent)
	}
	if from != dst.Format {
		if err := e.checkHeld(dst, d.ent); err != nil {
			return result(nil, err)
		}
	}
	return result(e.Encode(dst.Format, d.ent))
}

// convertCarrier writes a carrier of one format as a carrier pack's message
// (0.92 ruling 6). Every error is the call's, in phases: those that stop a
// decode, the other decode errors, the context, the encode.
func (e *Engine) convertCarrier(d *decodeState, run *runDecode, from string, dst *Pack, keys []string, context map[string]string) ([]byte, error) {
	if run.stop != nil {
		return nil, run.stop
	}
	failed := d.unforgiven(0, run.before)
	for i := range run.msgs {
		failed = append(failed, run.msgs[i].failed...)
	}
	failed = append(failed, d.unforgiven(run.before, len(d.failed))...)
	if len(failed) > 0 {
		return nil, &DecodeError{Format: from, Fields: failed}
	}
	if err := e.runItems(from, d, run); err != nil {
		return nil, err
	}
	vals, err := e.contextValues(keys, context)
	if err != nil {
		return nil, err
	}
	msgs := make([]*Entity, len(run.msgs))
	for i := range run.msgs {
		msgs[i] = joined(d.ent, run.msgs[i].ent)
		keepKinds(msgs[i], from, dst)
	}
	// The outer entity alone: the target's kind is chosen on it.
	outer := joined(d.ent, NewEntity())
	again := from != dst.Format || context != nil
	if from != dst.Format {
		outer.Kind = EntityKind{}
	}
	if again {
		fillValues(outer, keys, vals)
		e.Complete(outer)
	}
	c, err := builtCodec(dst)
	if err != nil {
		return nil, err
	}
	kind, format, err := c.runKind(dst, outer)
	if err != nil {
		return nil, err
	}
	fill := again
	if format != "" {
		fill = format != run.format || context != nil
	} else if len(msgs) != 1 {
		return nil, &Error{Kind: ErrMessageCount, Format: dst.Format, Detail: fmt.Sprintf("the kind %s takes exactly one message and the run has %d", kind, len(msgs))}
	}
	if fill {
		for _, m := range msgs {
			fillValues(m, keys, vals)
			e.Complete(m)
		}
	}
	// 0.94 ruling 7: once, on the kind chosen, the outer entity joined with
	// the first message, or alone for an empty run.
	if from != dst.Format {
		chk := outer
		if len(msgs) > 0 {
			chk = joined(outer, msgs[0])
		}
		// To a kind with a `run` line the messages' kinds are those of
		// inner messages: not a kept kind of the carrier (ruling 4). A kind
		// without one takes the one message, checked as `convert`: its
		// kinds, as kept by keepKinds, are those of ruling 4.
		c := *chk
		c.Kind, c.InnerKind = EntityKind{}, EntityKind{}
		if format == "" {
			c.Kind, c.InnerKind = msgs[0].Kind, msgs[0].InnerKind
		}
		chk = &c
		if err := e.checkHeldNamed(dst, kind, chk); err != nil {
			return nil, err
		}
	}
	if format != "" {
		return c.encodeRun(e, dst, outer, msgs)
	}
	msgs[0].Kind = EntityKind{Format: dst.Format, Name: kind}
	return e.encodeWith(dst, msgs[0])
}

// runItems bounds the items of all the joined entities of a run together
// (0.92 ruling 5): over the messages whose decode came to its end, a message
// whose result is a `transform-decode` included, the items of the outer
// entity once for each and each message's own items are summed. The sum may
// reach the limit; one item more is `malformed-wire` of the call. The outer
// entity is walked once, and each message once.
func (e *Engine) runItems(format string, d *decodeState, run *runDecode) error {
	outer := int64(0)
	for _, l := range d.ent.Lists {
		outer += deepItems(l)
	}
	sum := int64(0)
	for i := range run.msgs {
		m := &run.msgs[i]
		if m.stop != nil || m.ent == nil {
			continue
		}
		own := int64(0)
		for _, l := range m.ent.Lists {
			own += deepItems(l)
		}
		// The sum never passes the limit, so the subtractions cannot
		// overflow.
		if outer > e.maxItems-sum || own > e.maxItems-sum-outer {
			return &Error{Kind: ErrMalformedWire, Format: format, Detail: fmt.Sprintf("the items of the joined entities of the run exceed the limit of %d list items at message %d", e.maxItems, i+1)}
		}
		sum += outer + own
	}
	return nil
}
