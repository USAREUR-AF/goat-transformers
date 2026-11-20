package goatxf

import (
	"math"
	"math/big"
)

// Derive functions of spec/engine-spec.md, "Version 0.16: derive functions
// for time, distance and frames". None of them fails a conversion (ruling 1):
// every failure leaves the target absent.

// argOr returns the float of argument i, or 0 when the function has fewer.
func argOr(args []Value, i int, fl func(int) float64) float64 {
	if i < len(args) {
		return fl(i)
	}
	return 0
}

var (
	bigThousand = big.NewInt(1000)
	bigMillion  = big.NewInt(1000000)
)

// intResult range-checks an exact integer result (ruling 3).
func intResult(x *big.Int) (Value, bool) {
	if !x.IsInt64() {
		return Value{}, false
	}
	return Value{Kind: KindInt, I: x.Int64()}, true
}

// floorDiv sets q to floor(a / b), b > 0, exactly. big.Int.Div is Euclidean
// division, which for a positive divisor is the floor.
func floorDiv(a, b *big.Int) *big.Int {
	return new(big.Int).Div(a, b)
}

// deriveTime computes sec_of, nsec_of and ms_of in exact integers.
func deriveTime(name string, args []Value) (Value, bool) {
	switch name {
	case "sec_of":
		return intResult(floorDiv(big.NewInt(args[0].I), bigThousand))
	case "nsec_of":
		ms := big.NewInt(args[0].I)
		r := new(big.Int).Mul(bigThousand, floorDiv(ms, bigThousand))
		r.Sub(ms, r)
		return intResult(r.Mul(r, bigMillion))
	case "ms_of":
		r := new(big.Int).Mul(big.NewInt(args[0].I), bigThousand)
		r.Add(r, floorDiv(big.NewInt(args[1].I), bigMillion))
		return intResult(r)
	}
	return Value{}, false
}

// deriveIntSum is integer add and sub; a result outside 64 bits is absent.
func deriveIntSum(name string, a, b int64) (Value, bool) {
	x, y := big.NewInt(a), big.NewInt(b)
	if name == "add" {
		return intResult(x.Add(x, y))
	}
	return intResult(x.Sub(x, y))
}

// WGS 84 (spec 0.16, "The ellipsoid"). Variables, not constants: a Go
// constant expression is evaluated exactly, and these are doubles.
var (
	wgsA  float64 = 6378137
	wgsF          = 1 / 298.257223563
	wgsE2         = wgsF * (2 - wgsF)
	wgsB          = wgsA * (1 - wgsF)
)

// geo tracks whether every intermediate stayed finite (ruling 1).
type geo struct{ bad bool }

func (g *geo) v(x float64) float64 {
	if !finite(x) {
		g.bad = true
	}
	return x
}

// sqrt is the square root of ruling 1: a negative argument is a failure.
func (g *geo) sqrt(x float64) float64 {
	if x < 0 {
		g.bad = true
		return 0
	}
	return g.v(math.Sqrt(x))
}

// div fails on a zero divisor.
func (g *geo) div(a, b float64) float64 {
	if b == 0 {
		g.bad = true
		return 0
	}
	return g.v(a / b)
}

// radii returns sin φ, cos φ, N and M of a latitude in degrees.
func (g *geo) radii(lat float64) (sinP, cosP, n, m float64) {
	phi := g.v(lat * degToRad)
	sinP, cosP = math.Sin(phi), math.Cos(phi)
	w := g.v(1 - wgsE2*sinP*sinP)
	n = g.div(wgsA, g.sqrt(w))
	m = g.div(wgsA*(1-wgsE2), g.v(math.Pow(w, 1.5)))
	return
}

// deriveGeo computes the float functions of 0.16 other than add and sub.
func deriveGeo(name string, x0, x1, x2 float64) (float64, bool) {
	g := &geo{}
	for _, x := range []float64{x0, x1, x2} {
		g.v(x)
	}
	if g.bad {
		return 0, false
	}
	// Ruling 6: a latitude argument outside [-90, 90] leaves the target absent.
	latOK := func(lat float64) bool { return lat >= -90 && lat <= 90 }
	var r float64
	switch name {
	case "deg":
		r = x0 * radToDeg
	case "rad":
		r = x0 * degToRad
	case "deg_lat_of":
		if !latOK(x1) {
			return 0, false
		}
		_, _, _, m := g.radii(x1)
		r = g.div(x0, m) * radToDeg
	case "deg_lon_of":
		if !latOK(x1) {
			return 0, false
		}
		_, cosP, n, _ := g.radii(x1)
		c := math.Abs(cosP)
		if c <= 1e-12 {
			return 0, false
		}
		r = g.div(x0, g.v(n*c)) * radToDeg
	case "m_lat_of":
		if !latOK(x1) {
			return 0, false
		}
		_, _, _, m := g.radii(x1)
		r = x0 * degToRad * m
	case "m_lon_of":
		if !latOK(x1) {
			return 0, false
		}
		_, cosP, n, _ := g.radii(x1)
		r = x0 * degToRad * n * math.Abs(cosP)
	case "ecef_x", "ecef_y", "ecef_z":
		if !latOK(x0) {
			return 0, false
		}
		sinP, cosP, n, _ := g.radii(x0)
		lam := g.v(x1 * degToRad)
		switch name {
		case "ecef_x":
			r = (n + x2) * cosP * math.Cos(lam)
		case "ecef_y":
			r = (n + x2) * cosP * math.Sin(lam)
		default:
			r = (n*(1-wgsE2) + x2) * sinP
		}
	case "lon_of_ecef":
		if x0 == 0 && x1 == 0 {
			return 0, false
		}
		a := math.Atan2(x1, x0)
		r = a * radToDeg
		// Ruling 5: the range is (-180, 180].
		if a == -math.Pi || r <= -180 {
			r = 180
		}
	case "lat_of_ecef", "hae_of_ecef":
		phi, h, ok := heikkinen(g, x0, x1, x2)
		if !ok {
			return 0, false
		}
		if name == "lat_of_ecef" {
			r = phi * radToDeg
		} else {
			r = h
		}
	default:
		return 0, false
	}
	if g.bad || !finite(r) {
		return 0, false
	}
	return r, true
}

// heikkinen is the closed form of spec 0.16, in its order. ok is false when
// G <= 0 (ruling 2) or an intermediate fails (ruling 1).
func heikkinen(g *geo, x, y, z float64) (phi, h float64, ok bool) {
	a, b, e2 := wgsA, wgsB, wgsE2
	a2, b2 := a*a, b*b
	e4 := e2 * e2
	p := g.sqrt(g.v(x*x + y*y))
	z2 := g.v(z * z)
	p2 := g.v(p * p)
	F := g.v(54 * b2 * z2)
	G := g.v(p2 + (1-e2)*z2 - e2*(a2-b2))
	if g.bad || G <= 0 {
		return 0, 0, false
	}
	c := g.div(e4*F*p2, g.v(G*G*G))
	s := g.v(math.Cbrt(g.v(1 + c + g.sqrt(g.v(c*c+2*c)))))
	k := g.v(s + 1 + g.div(1, s))
	P := g.div(F, g.v(3*k*k*G*G))
	Q := g.sqrt(g.v(1 + 2*e4*P))
	// Ruling 9: a negative argument of this square root is taken as 0.
	arg := g.v(a2/2*(1+g.div(1, Q)) - g.div(P*(1-e2)*z2, g.v(Q*(1+Q))) - P*p2/2)
	if arg < 0 {
		arg = 0
	}
	r0 := g.v(g.div(-P*e2*p, 1+Q) + g.sqrt(arg))
	d := g.v(p - e2*r0)
	U := g.sqrt(g.v(d*d + z2))
	V := g.sqrt(g.v(d*d + (1-e2)*z2))
	z0 := g.div(b2*z, g.v(a*V))
	h = g.v(U * (1 - g.div(b2, g.v(a*V))))
	phi = g.v(math.Atan2(z+(a2-b2)/b2*z0, p))
	if g.bad {
		return 0, 0, false
	}
	return phi, h, true
}
