# SPDX-License-Identifier: GPL-3.0-only
"""One preparation path for curved-face contours, solids and Custom Features.

Dimensions describe local straight tools. Boundary curves are projected exactly
as rational NURBS; no polygonal replacement of source arcs/holes is performed.
Only renderer-owned preparations retain native temporary sheets.
"""
from dataclasses import dataclass, replace
import math

import adsk.core
import adsk.fusion

from . import model, clipping, solid
from . import geometry as geo
from . import surface_geometry as sg
from .cylindrical_geometry import enclosing_radius

TOLERANCE = model.TOLERANCE
ZONE_PARAMETERS = {
    'cylinder_start': ('Start Angle','deg'), 'cylinder_sweep': ('Sweep Angle','deg'),
    'axial_start': ('Axial Start','mm'), 'axial_length': ('Axial Length','mm'),
}


class LocalProjectionError(ValueError):
    """One aperture cannot be projected through its local surface fold."""


def is_curved(source):
    return isinstance(source,adsk.fusion.BRepFace) and not isinstance(source.geometry,adsk.core.Plane)


def supported(source):
    return is_curved(source) and not isinstance(source.geometry,(adsk.core.Sphere,adsk.core.Torus))


def point(p):
    return adsk.core.Point3D.create(*p)


def vector(p):
    return adsk.core.Vector3D.create(*p)


def matrix(origin,u,v,n):
    result = adsk.core.Matrix3D.create()
    result.setWithCoordinateSystem(point(origin),vector(u),vector(v),vector(n))
    return result


def normalized(config, component):
    result = dict(config)
    defaults = dict(surface=True, boundary='rectangle', width=8., height=6., material='cells',
        operation='cut', direction='one', reverse=True, start='0 mm',
        distance1=str(config.get('cut_depth',.2))+' cm', distance2='2 mm',
        taper1='0 deg',taper2='0 deg',extent1='distance',extent2='distance',
        target1=None,target2=None,center_point=None,cylinder_start=0.,cylinder_sweep=math.tau,
        axial_start=0.,axial_length=0.,bodies=[])
    for key,value in defaults.items():
        result.setdefault(key,value)
    units = component.parentDesign.unitsManager
    for key in ('start','distance1','distance2'):
        result['_'+key] = units.evaluateExpression(result[key],'mm') if isinstance(result[key],str) else result[key]
    return result


class Chart:
    """A finite source chart; revolved charts use physical meridian distances."""
    def __init__(self, source):
        self.source = model.native(source)
        if not supported(self.source):
            raise ValueError('Select a planar, cylindrical, conical, or smooth freeform face. Spheres and tori are not supported.')
        if not self.source.body.isSolid:
            raise ValueError('Curved-face perforation requires a solid body.')
        self.surface = self.source.geometry
        # The analytic geometry can use a different UV origin/direction from
        # its trimmed face (notably imported cylinders). Bounds and evaluations
        # must come from the same face evaluator.
        self.evaluator = self.source.evaluator
        box = self.source.evaluator.parametricRange()
        self.low,self.high = tuple(box.minPoint.asArray()),tuple(box.maxPoint.asArray())
        if not all(math.isfinite(v) for v in (*self.low,*self.high)) or any(b-a <= 1e-10 for a,b in zip(self.low,self.high)):
            raise ValueError('The source surface must have finite, nonsingular parameter bounds.')
        self.kind = ('cylinder' if isinstance(self.surface,adsk.core.Cylinder) else
                     'cone' if isinstance(self.surface,adsk.core.Cone) else 'freeform')
        ok,uv = self.evaluator.getParameterAtPoint(self.source.pointOnFace)
        if not ok:
            raise ValueError('Unable to locate the source surface.')
        _,_,_,raw = self._uv_frame(tuple(uv.asArray()))
        ok,normal = self.source.evaluator.getNormalAtPoint(self.source.pointOnFace)
        if not ok:
            raise ValueError('Unable to determine the source material side.')
        self.material_sign = 1 if sg.dot(raw,tuple(normal.asArray())) > 0 else -1
        self.closed = False
        self.slope = 0.
        self.singular_points=()
        if self.kind in ('cylinder','cone'):
            self._revolved()
        else:
            self.closed_u=self.source.evaluator.isClosedInU
            self.closed_v=self.source.evaluator.isClosedInV
            poles=[]
            for axis in (0,1):
                for boundary in (self.low[axis],self.high[axis]):
                    points=[]
                    for i in range(5):
                        uv=[0.,0.];uv[axis]=boundary
                        uv[1-axis]=self.low[1-axis]+(self.high[1-axis]-self.low[1-axis])*i/4
                        points.append(self._point(uv))
                    if all(sg.length(sg.sub(p,points[0]))<TOLERANCE for p in points[1:]):
                        poles.append(points[0])
            self.singular_points=tuple(poles)
            self.u_map=self._length_map(0,(self.low[1]+self.high[1])/2)
            self.v_map=self._length_map(1,(self.low[0]+self.high[0])/2)
            self._row_maps={round((self.low[1]+self.high[1])/2,12):self.u_map}
            self.width,self.height=self.u_map.total,self.v_map.total
            if min(self.width,self.height) <= TOLERANCE:
                raise ValueError('The source surface has a singular chart. Select a regular smooth region.')
            self.minimum_metric=math.inf
            self.normal_rate=0.
            for i in range(17):
                for j in range(17):
                    # A NURBS boundary can collapse to a single pole while its
                    # interior is regular. Validate interior samples; candidate
                    # tools that touch the undefined boundary frame are skipped
                    # individually below rather than rejecting the whole face.
                    uv=(self.low[0]+(self.high[0]-self.low[0])*(i+.5)/17,
                        self.low[1]+(self.high[1]-self.low[1])*(j+.5)/17)
                    ok,du,dv=self.evaluator.getFirstDerivative(adsk.core.Point2D.create(*uv))
                    if not ok:
                        raise ValueError('Unable to measure surface spacing.')
                    a=sg.mul(tuple(du.asArray()),(self.high[0]-self.low[0])/self.width)
                    b=sg.mul(tuple(dv.asArray()),(self.high[1]-self.low[1])/self.height)
                    aa,bb,ab=sg.dot(a,a),sg.dot(b,b),sg.dot(a,b)
                    eigen=(aa+bb-math.sqrt((aa-bb)**2+4*ab*ab))/2
                    self.minimum_metric=min(self.minimum_metric,math.sqrt(max(eigen,0)))
                    normal=self._uv_frame(uv)[3]
                    for axis,span in ((0,self.width),(1,self.height)):
                        next_uv=list(uv)
                        next_uv[axis]=min(self.high[axis],uv[axis]+(self.high[axis]-self.low[axis])/256)
                        if next_uv[axis]>uv[axis]:
                            rate=sg.length(sg.sub(self._uv_frame(next_uv)[3],normal))*256/span
                            self.normal_rate=max(self.normal_rate,rate)
            if self.minimum_metric<1e-5:
                raise ValueError('The source surface has a singular chart. Select a regular smooth region.')
        self.signature = (self.kind,self.low,self.high,self.width,self.height,self.material_sign,
                          tuple(self._point(self.low)),tuple(self._point(self.high)))

    def _length_map(self,axis,fixed):
        def speed(parameter):
            uv=(parameter,fixed) if axis==0 else (fixed,parameter)
            ok,du,dv=self.evaluator.getFirstDerivative(adsk.core.Point2D.create(*uv))
            if not ok:
                raise ValueError('Unable to measure the surface row length.')
            return (du if axis==0 else dv).length
        return sg.LengthMap(speed,self.low[axis],self.high[axis],TOLERANCE/100)

    def _row_map(self,v):
        v=max(self.low[1],min(self.high[1],v));key=round(v,12)
        if key not in self._row_maps:
            self._row_maps[key]=self._length_map(0,v)
        return self._row_maps[key]

    def _parameters(self,x,y):
        v=self.v_map.parameter_at(y)
        row=self._row_map(v)
        return row.parameter_at(x-self.width/2+row.total/2),v

    def physical_pitch(self,radius,gap,margin,low,high):
        pitch=2*radius+gap
        # Sample physical normal curvature, independently of UV speed. Ignore
        # patches that cannot accommodate the local trim envelope at all.
        for axis in (0,1):
            for fixed in (.2,.5,.8):
                for i in range(65):
                    uv=[0.,0.]
                    uv[axis]=self.low[axis]+(self.high[axis]-self.low[axis])*(.001+.998*i/64)
                    uv[1-axis]=self.low[1-axis]+(self.high[1-axis]-self.low[1-axis])*fixed
                    other=list(uv);other[axis]+=(self.high[axis]-self.low[axis])*1e-5
                    try:
                        p,_,_,n=self._uv_frame(uv);q,_,_,nn=self._uv_frame(other)
                    except sg.SingularTangentError:
                        continue
                    delta=sg.sub(q,p);distance=sg.dot(delta,delta)
                    if distance<1e-20:continue
                    curvature=sg.dot(sg.sub(nn,n),delta)/distance
                    if abs(curvature)*(radius+margin)>.8:continue
                    required=sg.arc_pitch(radius,gap,curvature,low,high)
                    if required is not None:pitch=max(pitch,required)
        return pitch+10*TOLERANCE

    def _point(self, uv):
        ok,p = self.evaluator.getPointAtParameter(adsk.core.Point2D.create(*uv))
        if not ok:
            raise ValueError('Unable to evaluate the source surface.')
        return tuple(p.asArray())

    def _uv_frame(self, uv):
        p = self._point(uv)
        ok,du,dv = self.evaluator.getFirstDerivative(adsk.core.Point2D.create(*uv))
        if not ok:
            raise ValueError('Unable to evaluate the surface tangents.')
        u = sg.unit(tuple(du.asArray()))
        n = sg.unit(sg.cross(tuple(du.asArray()),tuple(dv.asArray())))
        return p,u,sg.cross(n,u),n

    def _revolved(self):
        self.axis = sg.unit(tuple(self.surface.axis.asArray()))
        origin = tuple(self.surface.origin.asArray())
        p00 = self._point(self.low)
        p10 = self._point((self.high[0],self.low[1]))
        p01 = self._point((self.low[0],self.high[1]))
        self.ci = 1 if abs(sg.dot(sg.sub(p10,p00),self.axis)) > abs(sg.dot(sg.sub(p01,p00),self.axis)) else 0
        self.zi = 1-self.ci
        z0 = sg.dot(sg.sub(p00,origin),self.axis)
        pz = p10 if self.zi==0 else p01
        z1 = sg.dot(sg.sub(pz,origin),self.axis)
        self.zheight = abs(z1-z0)
        self.origin = sg.add(origin,sg.mul(self.axis,min(z0,z1)))
        def radial(p):
            delta = sg.sub(p,origin)
            return sg.sub(delta,sg.mul(self.axis,sg.dot(delta,self.axis)))
        lowp,highp = (p00,pz) if z0 <= z1 else (pz,p00)
        self.radius0,self.radius1 = sg.length(radial(lowp)),sg.length(radial(highp))
        if self.zheight <= TOLERANCE:
            raise ValueError('The source has no axial length.')
        self.slope = (self.radius1-self.radius0)/self.zheight
        self.slant = math.sqrt(1+self.slope*self.slope)
        angular_origin = list(self.low)
        angular_origin[self.zi] = (self.low[self.zi]+self.high[self.zi])/2
        first = sg.unit(radial(self._point(angular_origin)))
        sample = list(angular_origin)
        sample[self.ci] += (self.high[self.ci]-self.low[self.ci])*.001
        near = sg.unit(radial(self._point(sample)))
        delta = math.atan2(sg.dot(sg.cross(first,near),self.axis),sg.dot(first,near))
        self.sweep = abs(delta)*1000
        if abs(self.sweep-math.tau)<1e-7:
            self.sweep=math.tau
        if delta < 0:
            endpoint = list(angular_origin)
            endpoint[self.ci] = self.high[self.ci]
            first = sg.unit(radial(self._point(endpoint)))
        self.u,self.v = first,sg.cross(self.axis,first)
        self.radius = max(self.radius0,self.radius1)
        self.width,self.height = self.radius*self.sweep,self.zheight*self.slant
        self.closed = abs(self.sweep-math.tau)<1e-7
        # Revolved local frames use outward geometric normals and axial Y.
        actual = tuple(self.source.pointOnFace.asArray())
        rr = sg.unit(radial(actual))
        raw = sg.unit(sg.sub(rr,sg.mul(self.axis,self.slope)))
        _,normal = self.source.evaluator.getNormalAtPoint(self.source.pointOnFace)
        self.material_sign = 1 if sg.dot(raw,tuple(normal.asArray()))>0 else -1

    def frame(self,x,y):
        if self.kind=='freeform':
            uv = self._parameters(x,y)
            bounded=tuple(max(self.low[i],min(self.high[i],uv[i])) for i in (0,1))
            p,u,v,n=self._uv_frame(bounded)
            if bounded!=uv:
                ok,du,dv=self.evaluator.getFirstDerivative(adsk.core.Point2D.create(*bounded))
                if not ok:
                    raise ValueError('Unable to extend the surface boundary frame.')
                p=sg.add(p,sg.add(sg.mul(tuple(du.asArray()),uv[0]-bounded[0]),sg.mul(tuple(dv.asArray()),uv[1]-bounded[1])))
            return p,u,v,n
        angle,z = x/self.radius,y/self.slant
        radial = sg.add(sg.mul(self.u,math.cos(angle)),sg.mul(self.v,math.sin(angle)))
        u = sg.add(sg.mul(self.u,-math.sin(angle)),sg.mul(self.v,math.cos(angle)))
        n = sg.unit(sg.sub(radial,sg.mul(self.axis,self.slope)))
        p = sg.add(sg.add(self.origin,sg.mul(self.axis,z)),sg.mul(radial,self.radius0+self.slope*z))
        return p,u,sg.cross(n,u),n

    def chart_point(self,p):
        if self.kind=='freeform':
            ok,uv = self.evaluator.getParameterAtPoint(point(p))
            if not ok:
                raise ValueError('Start Point must lie on the selected smooth surface.')
            uv=uv.asArray()
            row=self._row_map(uv[1])
            return self.width/2+row.length_at(uv[0])-row.total/2,self.v_map.length_at(uv[1])
        delta=sg.sub(p,self.origin)
        return math.atan2(sg.dot(delta,self.v),sg.dot(delta,self.u))%math.tau*self.radius,sg.dot(delta,self.axis)*self.slant

    def project(self,frame,x,y,seed):
        """Inverse orthographic projection onto the exact underlying surface."""
        p,u,v,n = frame
        uv = list(seed)
        target = sg.add(p,sg.add(sg.mul(u,x),sg.mul(v,y)))
        periodic=((self.closed_u,self.closed_v) if self.kind=='freeform' else
                  tuple(self.closed and i==self.ci for i in (0,1)))
        for _ in range(20):
            uv=sg.projection_parameters(uv,self.low,self.high,periodic)
            try:q = self._point(uv)
            except (RuntimeError,ValueError) as error:
                raise LocalProjectionError('The local tool crosses a surface fold or parameter boundary. Reduce Pattern Scale or Distance.') from error
            residual = sg.sub(q,target)
            a,b = sg.dot(residual,u),sg.dot(residual,v)
            if math.hypot(a,b)<1e-10:
                return q,tuple(uv)
            try:ok,du,dv=self.evaluator.getFirstDerivative(adsk.core.Point2D.create(*uv))
            except RuntimeError as error:
                raise LocalProjectionError('The local tool crosses a surface fold or parameter boundary. Reduce Pattern Scale or Distance.') from error
            if not ok:
                break
            du,dv=tuple(du.asArray()),tuple(dv.asArray())
            aa,bb,cc,dd=sg.dot(du,u),sg.dot(dv,u),sg.dot(du,v),sg.dot(dv,v)
            determinant=aa*dd-bb*cc
            if abs(determinant)<1e-12:
                break
            uv[0]-=(dd*a-bb*b)/determinant
            uv[1]-=(-cc*a+aa*b)/determinant
        raise LocalProjectionError('The local tool crosses a surface fold or singularity. Reduce hole size or choose a smaller region.')

    def seed(self,x,y):
        if self.kind=='freeform':
            uv=self._parameters(x,y)
            return tuple(max(self.low[i],min(self.high[i],uv[i])) for i in (0,1))
        p=self.frame(x,y)[0]
        ok,uv=self.evaluator.getParameterAtPoint(point(p))
        if not ok:
            raise ValueError('Unable to locate a local tool on the surface.')
        return tuple(uv.asArray())


def validate(source, settings, config, chart=None):
    settings.validate()
    chart = chart or Chart(source)
    sg.validate_distribution(chart.kind, settings)
    if config['result']!='profiles' and model.source_component(source).parentDesign.designType!=adsk.fusion.DesignTypes.ParametricDesignType:
        raise ValueError('Curved solid operations require Capture Design History.')
    if config['material']!='cells':
        raise ValueError('Curved surfaces support Holes. Perforated Panel currently requires a planar source.')
    if any(config['extent'+side]!='distance' for side in ('1','2') if side=='1' or config['direction']=='two'):
        raise ValueError('Curved surfaces support Distance extents to keep local cuts bounded.')
    units = model.source_component(source).parentDesign.unitsManager
    if any(abs(units.evaluateExpression(config['taper'+side],'deg'))>1e-10 for side in ('1','2')):
        raise ValueError('Curved surfaces currently require zero Taper Angle.')
    if config['_distance1']<=0 or config['direction']=='two' and config['_distance2']<=0:
        raise ValueError('Distance must be positive.')
    if chart.kind!='freeform':
        low,high=intervals(chart,config)
        if max(abs(low),abs(high))>=chart.radius:
            raise ValueError('Distance and Start Offset must remain below the surface radius.')
        start,sweep=config['cylinder_start'],config['cylinder_sweep']
        if not 0 < sweep <= chart.sweep+1e-7 or not chart.closed and (start<0 or start+sweep>chart.sweep+1e-7):
            raise ValueError('Start Angle and Sweep Angle must fit the selected face.')
        length=config['axial_length'] or chart.zheight-config['axial_start']
        if config['axial_start']<0 or length<=0 or config['axial_start']+length>chart.zheight+1e-7:
            raise ValueError('Axial Start and Axial Length must fit the selected face. Use 0 length for the remaining height.')
    return chart


def project_curve(curve):
    if isinstance(curve,adsk.core.Line3D):
        a,b=curve.startPoint,curve.endPoint
        if math.hypot(b.x-a.x,b.y-a.y)<1e-9:
            return None
        return adsk.core.Line3D.create(adsk.core.Point3D.create(a.x,a.y,0),adsk.core.Point3D.create(b.x,b.y,0))
    nurbs=curve if isinstance(curve,adsk.core.NurbsCurve3D) else curve.asNurbsCurve
    ok,points,degree,knots,rational,weights,periodic=nurbs.getData()
    if not ok:
        raise ValueError('Unable to project an exact surface boundary curve.')
    points=[adsk.core.Point3D.create(p.x,p.y,0) for p in points]
    result=(adsk.core.NurbsCurve3D.createRational(points,degree,knots,weights,periodic) if rational else
            adsk.core.NurbsCurve3D.createNonRational(points,degree,knots,periodic))
    # A box/surface intersection is often stored as a spatial NURBS whose
    # orthographic projection is exactly a straight side of the box.
    ok,a,b=result.evaluator.getParameterExtents()
    ok_p,p=result.evaluator.getPointAtParameter(a);ok_q,q=result.evaluator.getPointAtParameter(b)
    if ok and ok_p and ok_q:
        dx,dy=q.x-p.x,q.y-p.y;length2=dx*dx+dy*dy
        if length2>1e-18 and all(abs((v.x-p.x)*dy-(v.y-p.y)*dx)<1e-9*math.sqrt(length2) and
            -1e-9<=((v.x-p.x)*dx+(v.y-p.y)*dy)/length2<=1+1e-9 for v in points):
            return adsk.core.Line3D.create(p,q)
    return result


def local_mask(source_body, frame, radius, margin, material_sign):
    manager=adsk.fusion.TemporaryBRepManager.get()
    inverse=matrix(*frame)
    inverse.invert()
    patch=manager.copy(source_body)
    if not manager.transform(patch,inverse):
        raise ValueError('Unable to position the local trim boundary.')
    size=radius+margin+10*TOLERANCE
    box=manager.createBox(adsk.core.OrientedBoundingBox3D.create(point((0,0,0)),vector((1,0,0)),vector((0,1,0)),
        2*size,2*size,4*size))
    if not manager.booleanOperation(patch,box,adsk.fusion.BooleanTypes.IntersectionBooleanType):
        raise ValueError('Unable to isolate the local surface boundary.')
    if not patch.faces.count:
        return None
    masks=[]
    for face in patch.faces:
        ok,normal=face.evaluator.getNormalAtPoint(face.pointOnFace)
        if not ok or normal.z*material_sign<=0:
            continue  # Never fill a near-side opening with the opposite patch.
        for edge in face.edges:
            evaluator=edge.evaluator
            ok,a,b=evaluator.getParameterExtents()
            if not ok:
                raise ValueError('Unable to inspect the local surface boundary.')
            for i in range(9):
                ok,p=evaluator.getPointAtParameter(a+(b-a)*(.01+.98*i/8))
                ok_n,n=face.evaluator.getNormalAtPoint(p) if ok else (False,None)
                if not ok_n or n.z*material_sign<.01:
                    # This site is not a single-valued local patch. Other sites
                    # on the same regular face can still fit full-sized tools.
                    return None
        loops=[]
        for loop in face.loops:
            curves=[project_curve(e.geometry) for e in loop.edges]
            loops.append([c for c in curves if c is not None])
        if loops and all(loops):
            masks.append(clipping.sheet(loops))
    if not masks:
        return None
    mask=merge(masks)
    if margin<=1e-9:
        return mask
    bounds=mask.boundingBox
    if min(bounds.maxPoint.x-bounds.minPoint.x,bounds.maxPoint.y-bounds.minPoint.y)<=2*margin+TOLERANCE:
        return None
    region=clipping.body_region(mask)
    rectangular=len(region.loops)==1 and len(region.loops[0].points)==4
    if rectangular:
        lo,hi=bounds.minPoint,bounds.maxPoint
        rectangular=all(min(abs(x-lo.x),abs(x-hi.x))<1e-7 and min(abs(y-lo.y),abs(y-hi.y))<1e-7 for x,y in region.loops[0].points)
    if rectangular:
        lo,hi=bounds.minPoint,bounds.maxPoint
        vertices=((lo.x+margin,lo.y+margin),(hi.x-margin,lo.y+margin),
                  (hi.x-margin,hi.y-margin),(lo.x+margin,hi.y-margin))
        return clipping.sheet([clipping.polygon_curves(vertices)])
    # Swept exclusions handle disappearing corners and narrow islands without
    # asking the native wire-offset solver to invert/collapse an entire loop.
    return erode_boundary(mask,margin)


def erode_boundary(mask,margin):
    """Conservative fallback for collapsing native offset wires.

    Keep the exact projected mask. Remove swept boundary neighborhoods instead
    of accepting a failed offset or filling an opening. Curve strokes have a
    bounded chord error; inflate their capsules by twice that tolerance.
    """
    manager=adsk.fusion.TemporaryBRepManager.get()
    result=manager.copy(mask)
    strips=[]
    for face in mask.faces:
        for edge in face.edges:
            points=model.strokes(edge.evaluator,lambda p:p)
            for a,b in zip(points,points[1:]):
                distance=math.dist(a,b)
                if distance<1e-10:
                    continue
                radius=margin+2*TOLERANCE
                cell=geo.Cell(center=((a[0]+b[0])/2,(a[1]+b[1])/2),shape='slot',size=2*radius,
                              length=distance+2*radius,angle=math.atan2(b[1]-a[1],b[0]-a[0]))
                strips.append(clipping.sheet([clipping.cell_curves(cell)]))
    if strips and not manager.booleanOperation(result,merge(strips),adsk.fusion.BooleanTypes.DifferenceBooleanType):
        raise ValueError('Unable to preserve Edge Offset around the surface boundary.')
    return result if result.faces.count and result.area>TOLERANCE*TOLERANCE else None


def merge(bodies):
    """Balanced union also preserves disjoint lumps for one updateBody call."""
    manager=adsk.fusion.TemporaryBRepManager.get()
    bodies=list(bodies)
    if not bodies:
        raise ValueError('No holes fit the selected surface and boundary settings.')
    while len(bodies)>1:
        next_level=[]
        for i in range(0,len(bodies),2):
            result=manager.copy(bodies[i])
            if i+1<len(bodies) and not manager.booleanOperation(result,bodies[i+1],adsk.fusion.BooleanTypes.UnionBooleanType):
                raise ValueError('Unable to combine the local surface tools.')
            next_level.append(result)
        bodies=next_level
    return bodies[0]


def zone_body(chart,config):
    manager=adsk.fusion.TemporaryBRepManager.get()
    body=manager.copy(chart.source)
    if chart.kind=='freeform':
        return body
    start=config['cylinder_start']%math.tau
    sweep=config['cylinder_sweep']
    z=config['axial_start']
    height=config['axial_length'] or chart.zheight-z
    if abs(sweep-math.tau)<1e-8 and z==0 and abs(height-chart.zheight)<1e-8:
        return body
    r=chart.radius*3+chart.zheight
    if abs(sweep-math.tau)<1e-8:
        curves=[adsk.core.Circle3D.createByCenter(model.point((0,0)),vector((0,0,1)),r)]
    else:
        a,b=(r*math.cos(start),r*math.sin(start)),(r*math.cos(start+sweep),r*math.sin(start+sweep))
        curves=[adsk.core.Line3D.create(model.point((0,0)),model.point(a)),
                adsk.core.Arc3D.createByCenter(model.point((0,0)),vector((0,0,1)),vector((1,0,0)),r,start,start+sweep),
                adsk.core.Line3D.create(model.point(b),model.point((0,0)))]
    volume=solid.extrude([clipping.sheet([curves])],z-1e-7,z+height+1e-7)
    manager.transform(volume,matrix(chart.origin,chart.u,chart.v,chart.axis))
    if not manager.booleanOperation(body,volume,adsk.fusion.BooleanTypes.IntersectionBooleanType):
        raise ValueError('Unable to restrict the surface Boundary zone.')
    return body


@dataclass
class Section:
    frame: tuple
    sheet: object
    cell: object
    seed: tuple
    low: float
    high: float


@dataclass
class Prepared:
    chart: Chart
    sections: tuple
    coordinates: tuple

    def body(self):
        manager=adsk.fusion.TemporaryBRepManager.get()
        tools=[]
        for section in self.sections:
            tool=solid.extrude([section.sheet],section.low,section.high)
            if not manager.transform(tool,matrix(*section.frame)):
                raise ValueError('Unable to position the local surface tool.')
            tools.append(tool)
        return merge(tools)


def projected_rim(chart,sheet,frame,seed):
    rim=[];min_z=max_z=0.
    for face in sheet.faces:
        for edge in face.edges:
            local=model.strokes(edge.evaluator,lambda p:p)
            previous=None;current_seed=seed
            for xx,yy in local:
                world,current_seed=chart.project(frame,xx,yy,current_seed)
                zz=sg.dot(sg.sub(world,frame[0]),frame[3])
                min_z,max_z=min(min_z,zz),max(max_z,zz)
                if previous is not None:rim.extend((*previous,*world))
                previous=world
    return rim,min_z,max_z


def intervals(chart,config):
    start=config['_start']*chart.material_sign
    d1,d2=config['_distance1'],config['_distance2']
    if config['direction']=='symmetric':
        return start-d1/2,start+d1/2
    if config['direction']=='two':
        return ((start-d2,start+d1) if chart.material_sign>0 else (start-d1,start+d2))
    direction=chart.material_sign*(-1 if config['reverse'] else 1)
    return (start-d1,start) if direction<0 else (start,start+d1)


def prepare(source,settings,config,chart=None):
    source=model.native(source)
    config=normalized(config,model.source_component(source))
    chart=validate(source,settings,config,chart)
    low,high=intervals(chart,config)
    depth=max(abs(low),abs(high),TOLERANCE)
    anchor=None
    if config.get('center_point') is not None:
        anchor=chart.chart_point(tuple(model.point_position(config['center_point'],model.source_component(source)).asArray()))
    if chart.kind!='freeform':
        ymin=config['axial_start']*chart.slant
        height=(config['axial_length'] or chart.zheight-config['axial_start'])*chart.slant
        sweep=config['cylinder_sweep']
        closed=abs(sweep-math.tau)<1e-8
        zone_anchor=(anchor[0]-config['cylinder_start']*chart.radius,anchor[1]-ymin) if anchor is not None else None
        if chart.kind=='cylinder' or settings.shape=='voronoi' or settings.shape in geo.ORGANIC_SHAPES or settings.layout=='circular':
            candidates=sg.periodic_cells(chart.radius,height,sweep,settings,depth,closed,zone_anchor)
            if chart.kind=='cone' and settings.shape in geo.ORGANIC_SHAPES:
                # Keep physical opening dimensions; redistribute center phases
                # by each local circumference instead of compressing tools at
                # the cone tip. Local axis/singularity guards still act below.
                adapted=[]
                for x,y,cell in candidates:
                    radius_at=chart.radius0+chart.slope*(y+ymin)/chart.slant
                    reach,meridian=sg.organic_axis_envelope(cell,chart.slope,chart.slant)
                    if radius_at+meridian<=depth+reach+TOLERANCE:continue
                    if closed:x=(x*chart.radius/radius_at) % (chart.radius*sweep)
                    adapted.append((x,y,cell))
                candidates=adapted
        else:
            region=sg.ConeRegion(chart.radius0,chart.slope,chart.radius,ymin,height,sweep)
            candidates=sg.conical_cells(region,settings,low,high,zone_anchor)
        shifted=[]
        for x,y,cell in candidates:
            x+=config['cylinder_start']*chart.radius
            shifted.append((x,y+ymin,cell))
        candidates=shifted
    else:
        region=geo.rectangle_region(chart.width,chart.height)
        layout=replace(settings,clip_boundary=True,margin=0,spread_radius=0,
            origin_x=anchor[0]-chart.width/2 if anchor else None,
            origin_y=anchor[1]-chart.height/2 if anchor else None)
        if settings.shape=='voronoi' or settings.shape in geo.ORGANIC_SHAPES:
            cells=geo.generate(region,layout)
        else:
            prototype=sg.tool_cell(settings)
            r=enclosing_radius(prototype)
            # UV speed/curvature can vary sharply at a remote edge. A global
            # worst-case pitch starves the whole face. Generate regular chart
            # sites and enforce full-sized tool separation in actual 3D below.
            pitch=chart.physical_pitch(r,settings.gap,settings.margin,low,high)
            centers=geo.generate(region,replace(layout,shape='circle',size=2*r,shape_angle=0,gap=pitch-2*r))
            cells=[]
            for c in centers:
                angle=settings.shape_angle+settings.grid_angle
                if settings.layout=='circular' and (settings.radial_orientation or settings.tangential_orientation):
                    angle+=math.atan2(c.center[1]-settings.offset_y,c.center[0]-settings.offset_x)
                    if settings.tangential_orientation:
                        angle+=math.pi/2
                cells.append(replace(prototype,center=c.center,angle=angle))
        candidates=[]
        seen=set()
        for c in cells:
            x,y=c.center[0]+chart.width/2,c.center[1]+chart.height/2
            if chart.closed_u:
                x%=chart.width
            if chart.closed_v:
                y%=chart.height
            key=(round(x,8),round(y,8))
            if key not in seen:
                seen.add(key)
                candidates.append((x,y,sg.local_cell(c)))
    if not candidates:
        raise ValueError('No holes fit the surface. Reduce hole size, Distance, or Edge Offset.')
    source_body=zone_body(chart,config)
    manager=adsk.fusion.TemporaryBRepManager.get()
    if settings.spread_radius>0:
        if settings.spread_radius<=settings.margin:
            raise ValueError('Spread Radius must be larger than Edge Offset.')
        cx,cy=anchor if anchor is not None else (chart.width/2,chart.height/2)
        center=chart.frame(cx+settings.offset_x,cy+settings.offset_y)[0]
        sphere=manager.createSphere(point(center),settings.spread_radius)
        if not manager.booleanOperation(source_body,sphere,adsk.fusion.BooleanTypes.IntersectionBooleanType):
            raise ValueError('Unable to limit the surface to Spread Radius.')
        if not source_body.faces.count:
            raise ValueError('Spread Radius leaves no surface for perforation.')
    sections=[]
    prepared=[]
    coordinates=[]
    rims=[]
    placements=[]
    material_probe = (manager.copy(source.body) if settings.shape in geo.ORGANIC_SHAPES
                      and settings.margin < 4*TOLERANCE else None)
    for x,y,cell in candidates:
        try:
            frame=chart.frame(x,y)
            seed=chart.seed(x,y)
        except sg.SingularTangentError:
            if chart.kind=='freeform':
                continue
            raise
        if chart.kind!='freeform':
            z=y/chart.slant
            radius_at=chart.radius0+chart.slope*z
            # A long axial fiber needs circumferential clearance, not the
            # enclosing disk of its entire length. Cone tips still act locally.
            reach,meridian=sg.organic_axis_envelope(cell,chart.slope,chart.slant)
            radius_at+=meridian
            if radius_at<=depth+reach+TOLERANCE:
                continue
        sections.append((frame,seed,cell))
        placements.append((*frame,low,high,enclosing_radius(cell)))
    if settings.shape!='voronoi' and settings.shape not in geo.ORGANIC_FIELDS:
        selected=sg.spaced_indices(placements,settings.gap)
        sections=[sections[i] for i in selected]
        placements=[placements[i] for i in selected]
    constraints=sg.separating_constraints(placements,settings.gap)
    for (frame,seed,cell),planes in zip(sections,constraints):
        if planes:
            if cell.shape=='voronoi':
                polygon=cell.vertices
                for nx,ny,bound in planes:
                    polygon=geo._clip_halfplane(polygon,nx,ny,bound)
                if len(polygon)<3:
                    continue
                cell=replace(cell,polygon=polygon)
            elif cell.shape not in geo.ORGANIC_FIELDS:
                # Repeating dimensions are never silently reduced to meet webs.
                points=cell.vertices if cell.shape in geo.POLYGON_SHAPES else (
                    cell.ellipse_points(96,enclosing=True) if cell.shape=='ellipse' else
                    tuple((enclosing_radius(cell)*math.cos(i*math.tau/96),enclosing_radius(cell)*math.sin(i*math.tau/96)) for i in range(96)))
                if any(any(nx*x+ny*y>bound+TOLERANCE for x,y in points) for nx,ny,bound in planes):
                    raise ValueError('Surface curvature reduces Web Thickness through Distance. Increase Web Thickness or reduce Distance.')
        sheet=clipping.sheet([clipping.cell_curves(cell)])
        if planes and cell.shape in geo.ORGANIC_FIELDS:
            # Scalar contours can be concave. Clip the exact sheet against a
            # convex separating mask, rather than applying a convex-polygon
            # algorithm to a concave loop. This also protects periodic seams.
            r=enclosing_radius(cell)+TOLERANCE
            polygon=((-r,-r),(r,-r),(r,r),(-r,r))
            for nx,ny,bound in planes:
                polygon=geo._clip_halfplane(polygon,nx,ny,bound)
            if len(polygon)<3:continue
            mask=clipping.sheet([clipping.polygon_curves(polygon)])
            if not manager.booleanOperation(sheet,mask,adsk.fusion.BooleanTypes.IntersectionBooleanType):
                raise ValueError('Unable to preserve the organic surface web.')
            if not sheet.faces.count or sheet.area<TOLERANCE*TOLERANCE:continue
        # A collapsed boundary inside the local trim box can project to a
        # self-intersecting wire. Omit that local site, not the regular face.
        size=enclosing_radius(cell)+settings.margin+10*TOLERANCE
        if cell.shape in geo.ORGANIC_FIELDS:
            padding=settings.margin+cell.curve_tolerance+10*TOLERANCE
            bounds=(min(p[0] for p in cell.vertices)-padding,max(p[0] for p in cell.vertices)+padding,
                    min(p[1] for p in cell.vertices)-padding,max(p[1] for p in cell.vertices)+padding)
        else:bounds=(-size,size,-size,size)
        if any(bounds[0]<=sg.dot(sg.sub(p,frame[0]),frame[1])<=bounds[1] and
               bounds[2]<=sg.dot(sg.sub(p,frame[0]),frame[2])<=bounds[3] and
               abs(sg.dot(sg.sub(p,frame[0]),frame[3]))<=2*size for p in chart.singular_points):
            continue
        mask=local_mask(source_body,frame,enclosing_radius(cell),settings.margin,chart.material_sign)
        if mask is None:
            continue
        outside=manager.copy(sheet)
        if not manager.booleanOperation(outside,mask,adsk.fusion.BooleanTypes.DifferenceBooleanType):
            raise ValueError('Unable to classify a surface boundary cell.')
        if outside.area>TOLERANCE*TOLERANCE:
            if not settings.clip_boundary:
                continue
            if not manager.booleanOperation(sheet,mask,adsk.fusion.BooleanTypes.IntersectionBooleanType):
                raise ValueError('Unable to trim a surface boundary cell.')
            if not sheet.faces.count or sheet.area<TOLERANCE*TOLERANCE:
                continue
            if cell.shape=='voronoi' and cell.corner_radius>0:
                sheet=clipping.rounded_body(sheet,cell.corner_radius)
        try:rim,min_z,max_z=projected_rim(chart,sheet,frame,seed)
        except (LocalProjectionError,sg.SingularTangentError):
            if cell.shape in geo.ORGANIC_FIELDS:continue
            raise
        a,b=low,high
        if config['_start']==0:
            if a<0 and b==0:
                b=max_z+TOLERANCE
            elif b>0 and a==0:
                a=min_z-TOLERANCE
        if config['_start']==0 and (a>=min_z-TOLERANCE or b<=max_z+TOLERANCE):
            if not (a<min_z+2*TOLERANCE and b>max_z-2*TOLERANCE):
                if cell.shape in geo.ORGANIC_FIELDS:
                    continue  # One overlong local normal tool must not reject the regular surface.
                raise ValueError('Distance is too small for the local surface curvature. Increase Distance.')
        if material_probe is not None:
            tool=solid.extrude([sheet],a,b)
            if not manager.transform(tool,matrix(*frame)):
                raise ValueError('Unable to check the organic boundary tool.')
            remaining=manager.copy(material_probe)
            if not manager.booleanOperation(remaining,tool,adsk.fusion.BooleanTypes.DifferenceBooleanType):
                raise ValueError('Unable to check material connectivity at the surface boundary.')
            if remaining.lumps.count>material_probe.lumps.count:
                continue
            material_probe=remaining
        # The one preparation supplies both preview rims and final straight solids.
        prepared.append(Section(frame,sheet,cell,seed,a,b))
        rims.append(tuple(rim))
        if len(prepared)>settings.limit:
            raise ValueError('The hole count exceeds Maximum Holes. Increase spacing or reduce the zone.')
    if not prepared:
        raise ValueError('No holes fit the surface with the current boundary and Edge Offset.')
    if settings.shape!='voronoi' and settings.shape not in geo.ORGANIC_FIELDS:
        actual=[(*s.frame,s.low,s.high,enclosing_radius(s.cell)) for s in prepared]
        selected=sg.spaced_indices(actual,settings.gap)
        prepared=[prepared[i] for i in selected]
        rims=[rims[i] for i in selected]
    coordinates=tuple(value for rim in rims for value in rim)
    return Prepared(chart,tuple(prepared),coordinates)


def make_body(source,settings,config):
    prepared=prepare(source,settings,config)
    return prepared.body(),len(prepared.sections)


def build(source,settings,config,prepared=None,source_snapshot=None,component=None):
    source=source if prepared is not None else model.native(source)
    component=component or model.source_component(source)
    config=normalized(config,component)
    prepared=prepared or prepare(source,settings,config)
    if config['result']=='profiles':
        sketch=component.sketches.addWithoutEdges(component.xYConstructionPlane)
        try:
            sketch.name='Perforation - Surface Contours'
            manager=adsk.fusion.TemporaryBRepManager.get()
            origin,u,v=model.sketch_frame(sketch)
            transform=matrix(origin,u,v,sg.cross(u,v))
            transform.invert()
            sketch.isComputeDeferred=True
            for section in prepared.sections:
                tool=solid.extrude([section.sheet],section.low,section.high)
                manager.transform(tool,matrix(*section.frame))
                patch=manager.copy(source_snapshot if source_snapshot is not None else source)
                if not manager.booleanOperation(patch,tool,adsk.fusion.BooleanTypes.IntersectionBooleanType):
                    raise ValueError('Unable to create surface contours.')
                for f in patch.faces:
                    for edge in f.edges:
                        curve=edge.geometry
                        nurbs=curve if isinstance(curve,adsk.core.NurbsCurve3D) else curve.asNurbsCurve
                        nurbs=nurbs.copy();nurbs.transformBy(transform)
                        sketch.sketchCurves.sketchFixedSplines.addByNurbsCurve(nurbs)
            sketch.isComputeDeferred=False
            return sketch,None,len(prepared.sections)
        except Exception:
            sketch.deleteMe()
            raise
    body=prepared.body()
    base=combine=occurrence=None
    combines=[]
    try:
        owner=component
        if config['operation']=='component':
            occurrence=component.occurrences.addNewComponent(adsk.core.Matrix3D.create())
            owner=occurrence.component
            owner.name='Perforation'
        base=owner.features.baseFeatures.add()
        base.name='Perfora Surface Geometry'
        base.startEdit()
        try:
            owner.bRepBodies.add(body,base)
        finally:
            base.finishEdit()
        if config['operation'] in ('cut','join','intersect'):
            targets=config['bodies'] or [source.body]
            for target in targets:
                tools=adsk.core.ObjectCollection.create()
                tools.add(base.bodies.item(0))
                data=component.features.combineFeatures.createInput(model.native(target),tools)
                data.operation={'cut':adsk.fusion.FeatureOperations.CutFeatureOperation,
                    'join':adsk.fusion.FeatureOperations.JoinFeatureOperation,
                    'intersect':adsk.fusion.FeatureOperations.IntersectFeatureOperation}[config['operation']]
                data.isKeepToolBodies=True
                combine=component.features.combineFeatures.add(data)
                combines.append(combine)
                if combine.healthState==adsk.fusion.FeatureHealthStates.ErrorFeatureHealthState:
                    raise ValueError(combine.errorOrWarningMessage)
                combine.name='Perforation ('+config['operation'].title()+')'
            base.bodies.item(0).isLightBulbOn=False
        prepared.created = tuple([base] + combines)
        return None,combine or base,len(prepared.sections)
    except Exception:
        for combine in reversed(combines):
            if combine.isValid:
                combine.deleteMe()
        if base and base.isValid:
            base.deleteMe()
        if occurrence and occurrence.isValid:
            occurrence.deleteMe()
        raise
