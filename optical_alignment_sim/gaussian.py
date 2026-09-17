"""General astigmatic, paraxial Gaussian beams (mm).

Q is the complex beam-parameter matrix, not its inverse. Grounding and scope:
docs/feedback-design.md. Immutable operations keep split branches independent.
"""
import math
import numpy as np


class GaussianQ:
    def __init__(self, matrix, axes):
        self.matrix = np.asarray(matrix, dtype=complex).reshape(2, 2).copy()
        self.axes = np.asarray(axes, dtype=float).reshape(2, 3).copy()

    @classmethod
    def circular(cls, q, direction):
        from .physics import transverse_basis
        return cls(np.eye(2)*q, transverse_basis(direction))

    def abcd(self, M):
        (a,b),(c,d) = M
        eye = np.eye(2)
        return GaussianQ((a*self.matrix+b*eye) @ np.linalg.inv(c*self.matrix+d*eye), self.axes)

    def lens(self, focal, powered_axis):
        axis = self.axes @ np.asarray(powered_axis)
        norm = np.linalg.norm(axis)
        if norm < 1e-9 or not focal:
            return self
        axis /= norm
        return GaussianQ(np.linalg.inv(np.linalg.inv(self.matrix)-np.outer(axis,axis)/focal), self.axes)

    def redirect(self, direction):
        from mathutils import Vector
        normal = Vector(np.cross(self.axes[0], self.axes[1])).normalized()
        rotation = normal.rotation_difference(Vector(direction).normalized())
        return GaussianQ(self.matrix, [tuple(rotation @ Vector(v)) for v in self.axes])

    def reflect(self, normal):
        """Reflect the physical transverse axes; restore a right-handed frame.

        A spatial reflection reverses handedness. Flipping the second coordinate
        and the corresponding Q row/column retains the physical ellipse/phase.
        """
        n = np.asarray(normal,dtype=float); n /= np.linalg.norm(n)
        axes = self.axes @ (np.eye(3)-2*np.outer(n,n))
        parity = np.diag([1.,-1.])
        return GaussianQ(parity @ self.matrix @ parity, parity @ axes)

    def precision(self, wavelength_nm, m2=1):
        """Intensity exp(-2 x.T P x), P eigenvalues = 1/w_i²."""
        return -math.pi*np.linalg.inv(self.matrix).imag/(wavelength_nm*1e-6*m2)

    def radii(self, wavelength_nm, m2=1):
        return 1/np.sqrt(np.linalg.eigvalsh(self.precision(wavelength_nm,m2)))

    def area_radius(self, wavelength_nm):
        a,b = self.radii(wavelength_nm)
        return math.sqrt(a*b)

    def marginal_radius(self, axis, wavelength_nm, m2=1):
        a = self.axes @ np.asarray(axis)
        return math.sqrt(max(0., float(a @ np.linalg.inv(self.precision(wavelength_nm,m2)) @ a)))

    def gouy(self):
        eig = np.linalg.eigvals(self.matrix)
        return float(sum(math.atan2(q.real,q.imag) for q in eig)/2)

    def pack(self):
        return {'real': self.matrix.real.tolist(), 'imag': self.matrix.imag.tolist(),
                'axes': self.axes.tolist()}

    @classmethod
    def unpack(cls, data):
        return cls(np.asarray(data['real'])+1j*np.asarray(data['imag']), data['axes'])

    def aperture(self, element, direction, hit, center, normal, wavelength, m2):
        """Whiten the Gaussian and integrate a projected aperture polygon.

        A circle is approximated by an inscribed 256-gon; the existing polygon
        integrator then sees a unit-radius circular Gaussian. This also handles
        rotated ellipses, off-center hits and oblique surface projection.
        """
        from mathutils import Vector
        from . import tracer, physics
        op = element.optics
        a = max(op.clear_aperture, 0)
        b = max(op.aperture_half_y, 0) if op.aperture_shape=='RECTANGULAR' else a
        if a==0 or b==0: return 0.
        e1,e2 = tracer._aperture_frame(element, normal)
        if op.aperture_shape=='CIRCULAR':
            angles = np.arange(256)*2*math.pi/256
            points = [(a*math.cos(t),a*math.sin(t)) for t in angles]
        else:
            points = [(a,b),(-a,b),(-a,-b),(a,-b)]
        vals, vecs = np.linalg.eigh(self.precision(wavelength,m2))
        whiten = (vecs*np.sqrt(vals)) @ vecs.T
        corners = []
        for x,y in points:
            delta = np.array(tuple(center-hit + x*e1 + y*e2))
            corners.append(tuple(whiten @ (self.axes @ delta)))
        return physics.polygon_aperture_overlap(corners, 1.)
