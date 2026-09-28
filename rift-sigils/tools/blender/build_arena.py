import bpy, math, random
from mathutils import Vector
random.seed(27)
def mat(name,color,metal=0,rough=.5,emission=0):
 m=bpy.data.materials.new(name);m.diffuse_color=(*color,1);m.use_nodes=True
 p=m.node_tree.nodes.get('Principled BSDF');p.inputs['Base Color'].default_value=(*color,1);p.inputs['Metallic'].default_value=metal;p.inputs['Roughness'].default_value=rough
 if emission: p.inputs['Emission Color'].default_value=(*color,1);p.inputs['Emission Strength'].default_value=emission
 return m
stone=mat('Ivory limestone',(.55,.61,.68),.15,.62)
dark=mat('Polished midnight blue',(.035,.073,.13),.72,.26)
gold=mat('Champagne gold inlay',(.72,.44,.13),.76,.28)
cyan=mat('Azure rift energy',(.03,.55,.95),.25,.27,2)
purple=mat('Royal violet banners',(.12,.045,.22),.05,.8)
grass=mat('Island moss',(.085,.2,.14),0,.95)
def mesh(name,verts,faces,material,parent=None):
 d=bpy.data.meshes.new(name);d.from_pydata(verts,[],faces);d.update();o=bpy.data.objects.new(name,d);bpy.context.collection.objects.link(o);o.data.materials.append(material);o.parent=parent;return o
cubeverts=[(-.5,-.5,-.5),(.5,-.5,-.5),(.5,.5,-.5),(-.5,.5,-.5),(-.5,-.5,.5),(.5,-.5,.5),(.5,.5,.5),(-.5,.5,.5)]
cubefaces=[(0,3,2,1),(4,5,6,7),(0,1,5,4),(1,2,6,5),(2,3,7,6),(3,0,4,7)]
templates={}
def box(name,loc,scale,material,parent=None):
 key=material.name
 if key not in templates:
  o=mesh(name,cubeverts,cubefaces,material,parent);templates[key]=o.data
 else:
  o=bpy.data.objects.new(name,templates[key]);bpy.context.collection.objects.link(o);o.parent=parent
 o.location=loc;o.scale=scale;return o
def ring(name,r,width,z,material,start=0,end=math.tau,n=160):
 verts=[]
 for i in range(n+1):
  a=start+(end-start)*i/n
  for rad in [r-width/2,r+width/2]:verts.append((math.cos(a)*rad,math.sin(a)*rad,z))
 return mesh(name,verts,[(i*2,i*2+1,i*2+3,i*2+2) for i in range(n)],material)
def cylinder(name,r,depth,z,material,n=128):
 vs=[(math.cos(i*math.tau/n)*r,math.sin(i*math.tau/n)*r,z+h) for h in [-depth/2,depth/2] for i in range(n)]
 fs=[tuple(range(n-1,-1,-1)),tuple(range(n,n*2))]+[(i,(i+1)%n,(i+1)%n+n,i+n) for i in range(n)]
 return mesh(name,vs,fs,material)
# Blender Z-up exports to Three Y-up. Camera on +X; fighters occupy +/-Y.
cylinder('Arena foundation',39,3,-1.55,dark)
for r in [18,27,35.5,38.6]:ring('Concentric gold circuit',r,.15,.02,gold)
for i in range(72):
 a=i*math.tau/72
 o=box('Radial floor engraving',(math.cos(a)*33,math.sin(a)*33,.015),(.08,3 if i%3==0 else 1,.035),gold);o.rotation_euler.z=a-math.pi/2
# A large physical gate card: 24 by 32 metres; a 14 metre fighter separation fits comfortably.
gate=bpy.data.objects.new('GateAssembly',None);bpy.context.collection.objects.link(gate)
box('Gate slab',(0,0,.18),(24,32,.36),dark,gate)
for x in [-11.85,11.85]:
 box('Gate gold long rail',(x,0,.4),(.22,31.8,.18),gold,gate)
 box('Gate luminous long seam',(x*.975,0,.44),(.06,31.3,.05),cyan,gate)
for y in [-15.85,15.85]:
 box('Gate gold short rail',(0,y,.4),(23.8,.22,.18),gold,gate)
for x in [-11.5,11.5]:
 for y in [-15.5,15.5]:
  o=box('Gate corner clasp',(x,y,.45),(1.05,1.05,.25),gold,gate);o.rotation_euler.z=math.pi/4
# Texture is supplied by the game; keep this named face separately addressable.
mesh('GateFace',[(-11.55,-15.5,.39),(11.55,-15.5,.39),(11.55,15.5,.39),(-11.55,15.5,.39)],[(0,1,2,3)],dark,gate)
# Rear half amphitheatre: actual tread/riser meshes, colonnades and small seating bays.
for tier in range(5):
 r=44+tier*3.1;z=1+tier*1.25
 ring('Terrace tread',r,2.9,z,stone,math.pi/2,math.pi*1.5,96)
 for i in range(49):
  a=math.pi/2+i*math.pi/48
  o=box('Tribune riser',(math.cos(a)*r,math.sin(a)*r,z-.55),(.3,3.7,1.1),dark);o.rotation_euler.z=a
  if i%2==0:
   o=box('Seat bench',(math.cos(a)*r,math.sin(a)*r,z+.3),(.6,2.4,.5),gold);o.rotation_euler.z=a
for i in range(13):
 a=math.pi*.55+i*math.pi*.9/12;r=63
 x,y=math.cos(a)*r,math.sin(a)*r;h=21+(i%3)*3
 box('Colonnade pedestal',(x,y,1.5),(5,5,3),dark)
 box('Fluted column core',(x,y,h/2),(2.6,2.6,h),stone)
 for dx,dy in [(-1.45,0),(1.45,0),(0,-1.45),(0,1.45)]:
  box('Column gold flute',(x+dx,y+dy,h/2),(.18,.18,h-2),gold)
 box('Column capital',(x,y,h),(4.4,4.4,1),gold)
 # Draped banner with a pointed bottom, towards arena.
 b=mesh('Hanging victory banner',[(-2.2,0,0),(2.2,0,0),(2.2,0,-8),(0,0,-10),(-2.2,0,-8)],[(0,1,2,3,4)],purple)
 b.location=(x+2,y,h-1);b.rotation_euler.z=a-math.pi/2
# Monumental skyline beyond the terraces; strong depth separation.
for i in range(9):
 y=(i-4)*20;x=-90-abs(i-4)*5;h=58 if i==4 else 27+(i*13)%25
 box('Sky citadel base',(x,y,5),(11,11,10),dark)
 box('Sky citadel tower',(x,y,h/2),(6,7,h),stone)
 box('Citadel central energy channel',(x+3.05,y,h/2),(.15,.25,h-4),cyan)
 for z in [h*.35,h*.7,h]:
  box('Citadel gold cornice',(x,y,z),(8,9,.6),gold)
 bpy.ops.mesh.primitive_cone_add(vertices=4,radius1=5,radius2=.5,depth=12,location=(x,y,h+6));bpy.context.object.name='Citadel crown';bpy.context.object.data.materials.append(stone)
for z,r in [(40,15),(52,21)]:
 o=ring('Orbital crown',r,.45,z,gold);o.location.x=-90
for i in range(16):
 x=-105-random.random()*60;y=random.uniform(-130,130);z=random.uniform(22,72);r=random.uniform(3,7)
 bpy.ops.mesh.primitive_cone_add(vertices=6,radius1=.3,radius2=r,depth=r*2.5,location=(x,y,z))
 o=bpy.context.object;o.name='Floating island rock';o.data.materials.append(stone)
 o=cylinder('Island moss cap',r,.7,0,grass,12);o.location=(x,y,z+r*1.25)
 box('Island shrine',(x,y,z+r*1.25+3),(1.5,1.5,6),stone)
# Delivery camera and portable light rig.
bpy.ops.object.camera_add(location=(46,-5,20));cam=bpy.context.object;cam.name='Arena delivery camera';cam.rotation_euler=(Vector((-7,0,8))-cam.location).to_track_quat('-Z','Y').to_euler();cam.data.lens=30;bpy.context.scene.camera=cam
for name,loc,power,color in [('Warm sun',(20,-25,50),3,(1,.83,.62)),('Cool fill',(0,30,25),1.4,(.55,.76,1))]:
 bpy.ops.object.light_add(type='SUN',location=loc);o=bpy.context.object;o.name=name;o.data.energy=power;o.data.color=color;o.rotation_euler=(Vector((0,0,0))-o.location).to_track_quat('-Z','Y').to_euler();o.data.angle=.12
scene=bpy.context.scene;scene.world=bpy.data.worlds.new('Celestial daylight');scene.world.color=(.25,.36,.5);scene.render.engine='BLENDER_EEVEE';scene.render.resolution_x=1100;scene.render.resolution_y=650;scene.render.resolution_percentage=100
result={'gate_size':[24,32],'arena_diameter':78,'objects':len(bpy.data.objects),'camera':list(cam.location)}

