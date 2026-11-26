package goatxf

// The check of spec 0.94: a conversion into a pack that has message kinds
// writes a kind only when the entity holds one of that kind's keys.

import "fmt"

// checkHeld is the check of 0.94 made by convert with from different from to,
// after the context and the derivations and before any line is written: the
// kind encode chooses for ent, and the error no-kind when ent holds no key of
// it. When choosing fails the check passes, so that encode reports the
// no-kind of choosing (ruling 5).
func (e *Engine) checkHeld(p *Pack, ent *Entity) error {
	if !p.HasKinds() {
		return nil // ruling 4 and 6: a pack without message kinds
	}
	// The kind encode chooses (0.5; Encode of 0.34 for a recorded inner
	// kind).
	if ent.Kind.Format != p.Format && ent.InnerKind.Format == p.Format {
		c := *ent
		c.Kind = ent.InnerKind
		ent = &c
	}
	if p.seq {
		c, err := builtCodec(p)
		if err != nil || c.pickKind == nil {
			return nil
		}
		k, err := c.pickKind(p, ent)
		if err != nil || k == nil {
			return nil
		}
		return e.checkSeqKind(p, k, ent)
	}
	lay, err := chooseEncode(p, ent)
	if err != nil || lay.kind == nil {
		return nil
	}
	if kept(ent, p, nil) {
		return nil
	}
	held := heldKeys(ent)
	keys := []string{}
	var walk func(lines []line)
	walk = func(lines []line) {
		for _, ln := range lines {
			switch {
			case ln.f != nil:
				keys = append(keys, ln.f.Key)
			case ln.g != nil:
				// A list counts by its entry, not by its item keys.
				keys = append(keys, ln.g.List+"[]")
			}
		}
	}
	walk(p.common)
	walk(lay.kind.lines)
	return e.heldVerdict(p, lay.kind.Name, keys, lay.kind.reqs, held, ent)
}

// checkSeqKind is the check on kind k of a sequential pack.
func (e *Engine) checkSeqKind(p *Pack, k *seqKind, ent *Entity) error {
	keys := []string{}
	inners := map[string]bool{}
	var walk func(nodes []*seqNode)
	walk = func(nodes []*seqNode) {
		for _, n := range nodes {
			switch n.op {
			case seqWhen:
				if n.key != "" {
					keys = append(keys, n.key) // 0.30 ruling 24
				}
			case seqField:
				keys = append(keys, n.f.Key)
				for _, a := range n.f.also {
					keys = append(keys, a.Key)
				}
			case seqGroup:
				keys = append(keys, n.g.List+"[]")
			case seqSwitchOp:
				for _, c := range n.sw.cases {
					walk(c.body)
				}
				if n.sw.els != nil {
					walk(n.sw.els.body)
				}
			case seqInner:
				inners[n.inner] = true
				// The model_keys of the inner pack; one that does not
				// pass the checks of 0.34 adds nothing.
				if in, err := e.innerPack(p, n.inner, false); err == nil {
					keys = append(keys, in.ModelKeys()...)
				}
			default:
				walk(n.body)
			}
		}
	}
	walk(p.sbody.common)
	walk(k.whens)
	walk(k.nodes)
	if kept(ent, p, inners) {
		return nil
	}
	return e.heldVerdict(p, k.name, keys, k.requires, heldKeys(ent), ent)
}

// kept reports whether the entity records a kept kind (ruling 4): Kind or
// InnerKind names to, or the format of an `inner` line of the chosen kind or
// of the common lines.
func kept(ent *Entity, p *Pack, inners map[string]bool) bool {
	for _, f := range []string{ent.Kind.Format, ent.InnerKind.Format} {
		if f != "" && (f == p.Format || inners[f]) {
			return true
		}
	}
	return false
}

// heldKeys is what the entity holds, as the text of keys of a kind: each of
// its own keys, and `<list>[]` for each list with at least one item.
func heldKeys(ent *Entity) map[string]bool {
	held := map[string]bool{}
	for k := range ent.Fields {
		held[k] = true
	}
	for l, items := range ent.Lists {
		if len(items) > 0 {
			held[l+"[]"] = true
		}
	}
	return held
}

// heldVerdict is no-kind unless the entity holds one of keys or one of the
// keys of the kind's `requires` terms (a key, or a list with an item).
func (e *Engine) heldVerdict(p *Pack, kind string, keys []string, reqs []*reqTerm, held map[string]bool, ent *Entity) error {
	for _, k := range keys {
		if held[k] {
			return nil
		}
	}
	for _, t := range reqs {
		if _, ok := ent.Fields[t.key]; ok || len(ent.Lists[t.key]) > 0 {
			return nil
		}
	}
	return &Error{Kind: ErrNoKind, Format: p.Format, Detail: fmt.Sprintf("the entity holds no key of kind %q", kind)}
}

// checkHeldNamed is the check on the kind named kind of a sequential carrier
// pack (ruling 7 of 0.94), on ent.
func (e *Engine) checkHeldNamed(p *Pack, kind string, ent *Entity) error {
	if !p.HasKinds() || !p.seq {
		return nil
	}
	for _, k := range p.sbody.kinds {
		if k.name == kind {
			return e.checkSeqKind(p, k, ent)
		}
	}
	return nil
}
