#!/usr/bin/env python3
"""Rebuild the native architecture SVGs and their logical Mermaid companions.

Usage: python scripts/render_architecture.py
No network, raster generation or external render process. Official AWS originals
remain under docs/assets/aws; nested vector IDs are scoped only in the diagrams.
"""
import argparse
from copy import deepcopy
from pathlib import Path
from xml.etree import ElementTree as ET

ASSETS = Path(__file__).resolve().parents[1] / 'docs' / 'assets'
NS = 'http://www.w3.org/2000/svg'
ET.register_namespace('', NS)
ICONS = {
 'alb':'Res_Elastic-Load-Balancing_Application-Load-Balancer_48.svg',
 'dns':'Arch_Amazon-Route-53_64.svg','ecs':'Arch_Amazon-Elastic-Container-Service_64.svg',
 'fargate':'Arch_AWS-Fargate_64.svg','rds':'Arch_Amazon-RDS_64.svg',
 'proxy':'Res_Amazon-RDS-Proxy-Instance_48.svg','valkey':'Res_Amazon-ElastiCache_ElastiCache-for-Valkey_48.svg',
 'cache':'Arch_Amazon-ElastiCache_64.svg','s3':'Arch_Amazon-Simple-Storage-Service_64.svg',
 'scan':'Arch_Amazon-GuardDuty_64.svg','mq':'Arch_Amazon-MQ_64.svg',
 'bedrock':'Arch_Amazon-Bedrock_64.svg','ecr':'Arch_Amazon-Elastic-Container-Registry_64.svg',
 'vpc':'Arch_Amazon-Virtual-Private-Cloud_64.svg','private':'Arch_AWS-PrivateLink_64.svg',
 'iam':'Arch_AWS-Identity-and-Access-Management_64.svg','secrets':'Arch_AWS-Secrets-Manager_64.svg',
 'kms':'Arch_AWS-Key-Management-Service_64.svg','logs':'Arch_Amazon-CloudWatch_64.svg',
 'acm':'Arch_AWS-Certificate-Manager_64.svg',
}


def element(parent, tag, **attrs):
    return ET.SubElement(parent, '{'+NS+'}'+tag, {key.replace('_','-'):str(value) for key,value in attrs.items()})


class Diagram:
    def __init__(self, name, title, subtitle, description, height):
        self.name,self.title,self.description,self.height=name,title,description,height
        self.nodes,self.edges={},[]
        self.root=ET.Element('{'+NS+'}svg',{'width':'1060','height':str(height),'viewBox':f'0 0 1060 {height}','role':'img','aria-labelledby':'title desc'})
        element(self.root,'title',id='title').text=title
        element(self.root,'desc',id='desc').text=description
        defs=element(self.root,'defs')
        marker=element(defs,'marker',id='arrow',viewBox='0 0 10 10',refX=9,refY=5,markerWidth=7,markerHeight=7,orient='auto-start-reverse')
        element(marker,'path',d='M0 0L10 5L0 10Z',fill='#37566b')
        element(self.root,'style').text='text{font-family:Arial,Helvetica,sans-serif;fill:#173146}.title{font-size:26px;font-weight:700}.label{font-size:20px;font-weight:700}.body{font-size:18px}.small{font-size:16px;fill:#41596b}.edge{fill:none;stroke:#37566b;stroke-width:2.3;marker-end:url(#arrow)}.wake{stroke-dasharray:6 5}'
        element(self.root,'rect',width=1060,height=height,fill='#fff')
        self.lines=element(self.root,'g',id='connections')
        self.boxes=element(self.root,'g',id='services')
        self.annotations=element(self.root,'g',id='annotations')
        self.text(32,42,title,'title')
        self.text(32,74,subtitle,'small')

    def text(self,x,y,value,cls='body',parent=None):
        element(self.annotations if parent is None else parent,'text',x=x,y=y,**{'class':cls}).text=value

    def icon(self,key,x,y,size=42):
        original=ET.parse(ASSETS/'aws'/ICONS[key]).getroot()
        nested=deepcopy(original)
        nested.attrib.update(x=str(x),y=str(y),width=str(size),height=str(size))
        prefix=f'{self.name}_{key}_{x}_{y}_'
        ids={node.attrib['id']:prefix+node.attrib['id'] for node in nested.iter() if 'id' in node.attrib}
        for node in nested.iter():
            for attr,value in list(node.attrib.items()):
                if attr=='id':node.set(attr,ids[value])
                else:
                    for old,new in ids.items():
                        value=value.replace('url(#'+old+')','url(#'+new+')')
                        if value=='#'+old:value='#'+new
                    node.set(attr,value)
        self.boxes.append(nested)

    def node(self,key,x,y,w,h,title,lines,icons=(),tone='normal'):
        self.nodes[key]=(title,lines,icons)
        group=element(self.boxes,'g',id=key)
        element(group,'rect',x=x,y=y,width=w,height=h,rx=10,fill='#f8f6f0' if tone=='control' else '#f0f7f8',stroke='#8ba4b4')
        self.text(x+72 if icons else x+18,y+39,title,'label',group)
        for i,icon in enumerate(icons):self.icon(icon,x+16 if i==0 else x+w-58,y+15)
        for i,line in enumerate(lines):self.text(x+18,y+79+26*i,line,'body',group)

    def edge(self,source,target,points,label='',at=None,wake=False,both=False):
        path='M'+'L'.join(f'{x} {y}' for x,y in points)
        attrs={'class':'edge wake' if wake else 'edge','d':path}
        if both:attrs['marker-start']='url(#arrow)'
        element(self.lines,'path',**attrs)
        self.edges.append((source,target,label,wake,both))
        if label and at:
            # White label ground preserves separation from crossing stems.
            self.text(*at,label,'small')

    def foot(self,y,*lines):
        for i,line in enumerate(lines):self.text(32,y+26*i,line,'small')

    def save(self,aliases=()):
        ET.indent(self.root,space='  ')
        raw=ET.tostring(self.root,encoding='unicode')+'\n'
        for name in (self.name,*aliases):(ASSETS/(name+'.svg')).write_text(raw)
        lines=['%% Logical companion to the native SVG; generated from the same service/edge definitions.','flowchart TB','  accTitle: '+self.title,'  accDescr: '+self.description]
        for key,(title,body,icons) in self.nodes.items():
            label='<br/>'.join([title,*body]).replace('"',"'")
            lines.append(f'  {key}["{label}"]')
        for source,target,label,wake,both in self.edges:
            arrow='<-->' if both else '-.->' if wake else '-->'
            lines.append(f'  {source} {arrow}'+(f'|"{label}"|' if label else '')+f' {target}')
        (ASSETS/(self.name+'.mmd')).write_text('\n'.join(lines)+'\n')


def overview(cloud=False):
    name='enterprise-context' if cloud else 'architecture'
    title='AWS: one comparison, seven business steps' if cloud else 'One comparison, seven business steps'
    subtitle='Terraform-defined · small configurable start · business handoffs, not provisioned capacity' if cloud else 'Compose runtime · asynchronous work · durable originals, outcomes and browser delivery'
    d=Diagram(name,title,subtitle,'Submit to acceptance, durable outbox, confirmed queue, leased processing and atomic outcome. A durable owner event reaches React over SSE; targeted API reads return saved results. SQL transport and delivery are expanded in the focused views.',970)
    common=[
     ('Submit',32,115,'1  Submit',['HTTPS entry + React','Session, CSRF, retry key','ALB → ECS/Fargate app'] if cloud else ['React + nginx :8088','Session, CSRF, retry key','Accepted work runs separately'],('alb','ecs') if cloud else ()),
     ('Accept',386,115,'2  Accept',['Django: supply + owner checks','Reserve → upload → finalize','Queued Job + durable Outbox'],('fargate',) if cloud else ()),
     ('Relay',740,115,'3  Relay',['Read committed dispatches','Reuse confirmed producer','Publish UUID; mark after confirm'],('fargate',) if cloud else ()),
     ('Queue',740,335,'4  Queue',['Amazon MQ: RabbitMQ quorum','Persistent UUID deliveries','Retries preserve logical identity'] if cloud else ['RabbitMQ quorum queue','Persistent UUID deliveries','Retries preserve logical identity'],('mq',) if cloud else ()),
     ('Process',386,335,'5  Process',['Fetch clean source; parse/cache','Converse → validate quotes','Current lease fences completion'],('fargate','bedrock') if cloud else ()),
     ('Save',32,335,'6  Save',['One PostgreSQL transaction','Outcome + report + inbox','Owner revision + StreamEvent'],('rds',) if cloud else ()),
     ('Read',32,575,'7  Read',['EventSource wakes React','GET affected state via Django','Open saved notification/result'],()),
     ('Delivery',386,575,'Delivery plane',['Ledger → event-relay → shards','Raw ASGI gateway → SSE','Durable replay after reconnect'],('fargate','valkey') if cloud else ()),
     ('Source',740,575,'Source gate',['Private S3 + GuardDuty gate','Checksum + clean-tag access','Separate original lifecycle view'] if cloud else ['SeaweedFS retains originals','ClamAV before parse/download','Local HTTP Converse provider'],('s3','scan') if cloud else ()),
    ]
    for key,x,y,label,body,icons in common:d.node(key,x,y,290,170,label,body,icons)
    d.edge('Submit','Accept',[(322,200),(384,200)])
    d.edge('Accept','Relay',[(676,200),(738,200)])
    d.edge('Relay','Queue',[(885,285),(885,333)])
    d.edge('Queue','Process',[(740,420),(678,420)])
    d.edge('Process','Save',[(386,420),(324,420)])
    d.edge('Save','Delivery',[(177,505),(177,540),(531,540),(531,573)],'Committed change',(190,531))
    d.edge('Delivery','Read',[(386,660),(324,660)],'SSE',(336,649))
    d.edge('Accept','Read',[(531,285),(531,310),(353,310),(353,555),(177,555),(177,573)],'202 receipt',(360,553),wake=True)
    if cloud:
        d.node('SQL',32,795,998,100,'Shared SQL ingress',['RDS Proxy carries ordinary writes and read-only gateway replay; bootstrap connects directly.'],('proxy',))
    else:
        d.node('Logs',32,795,998,100,'Correlated operations',['API, relays, worker, provider and gateway emit safe lifecycle metadata to OpenObserve OSS.'],tone='control')
    d.foot(930,'7 starts with the acceptance receipt and overlaps3–6. Retries recover accepted work; new logical work can receive429/503.'.replace('overlaps3','overlaps 3').replace('receive429','receive 429'))
    d.save(('architecture-completion',) if not cloud else ())


def event_delivery():
    d=Diagram('event-delivery','From committed state to browser','7 Read · durable owner state is authoritative; Valkey carries wake signals',
        'The same transaction persists visible state and an owner revision. Event-relay publishes owner wakes to a fixed Valkey shard. A bounded raw ASGI gateway subscribes before replay and sends SSE. React reads affected state through the owner-scoped API; resets and reconnect snapshots recover state.',1015)
    d.node('Persist',32,120,460,170,'7a  Persist',['PostgreSQL: revision + StreamEvent','Same transaction as visible changes','Indexed durable intent; owner-scoped order'])
    d.node('Publish',568,120,460,170,'7b  Publish wake',['Event-relay: bounded SKIP LOCKED batches','Publish owner wake, then mark published','Retry from the ledger after interruption'])
    d.node('Gateway',32,390,460,170,'7c  Deliver change',['Raw ASGI gateway replicas','Subscribe ACK → indexed SQL replay','Bounded DB work; no heartbeat SQL'])
    d.node('Shards',568,390,460,170,'Fixed Valkey shards',['owner_id % shard_count; same ordered map','Shared subscriptions; coalesced wake queues','Missed wake → replay from PostgreSQL'])
    d.node('React',32,680,460,170,'React browser',['EventSource receives revision + kind + IDs','Coalesce affected job/document/inbox reads','Render saved state and completion notifications'])
    d.node('API',568,680,460,170,'7d  Read affected state',['Targeted owner-scoped Django GET','Saved job/report, document metadata or inbox','SSE gateway never mutates application records'])
    d.edge('Persist','Publish',[(492,205),(566,205)])
    d.edge('Publish','Shards',[(798,290),(798,388)],'Owner-channel wake',(808,341),wake=True)
    d.edge('Shards','Gateway',[(568,475),(494,475)],'Wake',(500,464),wake=True)
    d.edge('Persist','Gateway',[(260,290),(260,388)],'Replay by revision',(274,341))
    d.edge('Gateway','React',[(260,560),(260,678)],'SSE: change / ready / reset',(274,624))
    d.edge('React','API',[(492,740),(566,740)],'GET',(507,730))
    d.edge('API','React',[(798,850),(798,886),(260,886),(260,852)],'Saved state',(480,909))
    d.foot(953,'Initial/reconnect snapshots recover current state. Retention gaps emit reset; session revocation ends the stream.',
           'Admission and replay have bounded queues, per-owner socket caps and explicit429/503 backpressure.'.replace('explicit429','explicit 429'))
    d.save()


def aws_delivery():
    d=Diagram('aws-event-delivery','AWS: dedicated delivery and shared SQL ingress','Terraform-defined · exact ALB SSE route · small configurable service counts',
        'PostgreSQL outcomes and durable owner events share a transaction. Event-relay accesses the ledger through RDS Proxy, publishes to fixed independent ElastiCache for Valkey shards, and a dedicated Fargate raw ASGI gateway replays with a read-only database role. ALB routes SSE separately from targeted Django API reads.',1110)
    d.node('DB',32,120,290,170,'7a  Persist',['RDS PostgreSQL','Outcome + revision + event','Durable application authority'],('rds',))
    d.node('Proxy',386,120,290,170,'RDS Proxy',['Shared bounded SQL ingress','App writer / stream reader','Verified TLS + role defaults'],('proxy',))
    d.node('Relay',740,120,290,170,'7b  Publish',['Event-relay on ECS/Fargate','Indexed ledger batches','Mark after owner wake'],('fargate',))
    d.node('Gateway',32,405,460,170,'7c  Deliver change',['Dedicated raw ASGI gateway on ECS/Fargate','Read-only replay; bounded shared DB pool','Session + owner checks; global socket leases'],('fargate',))
    d.node('Cache',568,405,460,170,'Fixed independent shards',['ElastiCache for Valkey: private TLS primaries','Stable owner hash; shared subscriptions','Missed wakes recover from durable replay'],('valkey','cache'))
    d.node('Browser',32,710,460,170,'React browser',['One EventSource per visible authenticated tab','Change IDs coalesce targeted REST reads','Render saved result and durable inbox'])
    d.node('ALB',568,710,460,170,'7d  Route + read',['ALB: /api/events/ → gateway:8001','Other paths → app:8080 → Django','Owner-scoped saved-state response'],('alb','ecs'))
    d.edge('Relay','Proxy',[(740,205),(678,205)],'SQL',(690,194))
    d.edge('Proxy','DB',[(386,205),(324,205)],'SQL',(337,194))
    d.edge('Gateway','Proxy',[(260,405),(260,343),(531,343),(531,292)],'Indexed read-only replay',(274,333))
    d.edge('Relay','Cache',[(885,290),(885,403)],'Owner wake',(895,350),wake=True)
    d.edge('Cache','Gateway',[(568,490),(494,490)],'Wake',(500,479),wake=True)
    d.edge('ALB','Gateway',[(798,710),(798,635),(260,635),(260,577)],'SSE request / streamed response',(370,624),both=True)
    d.edge('Browser','ALB',[(492,795),(566,795)],'HTTPS',(499,784),both=True)
    d.node('Recovery',32,945,998,100,'Recovery and isolation',['Gateway SQL uses resume_stream; ordinary transactions use resume_app; nonlogin ownership stays in bootstrap.'],tone='control')
    d.foot(1083,'Heartbeat keeps the ALB connection active. Shard-map changes require a coordinated gateway drain and ledger replay.')
    d.save()


def inspection():
    d=Diagram('service-inspection','Inspect the local runtime','Authenticated operator viewers · web listeners bind 127.0.0.1',
        'RabbitMQ Management inspects queue metrics, Flower observes transport task events, pgAdmin reads seven allowlisted application tables, Redis Commander inspects both Valkey shards, and the storage admin can read privileged original bytes. OpenObserve correlates safe lifecycle and delivery metadata.',1145)
    rows=[
      ('Queue','RabbitMQ quorum',['Persistent UUID deliveries','Separate from application result status'],'BrokerView','RabbitMQ Management',[':15672 · lab_monitor','Queue/consumer metrics; no queue payload access']),
      ('Worker','Celery worker',['Leased, idempotent application effects','Transport task events sent through RabbitMQ'],'Flower','Flower',[':5555 · read-only task history','Task SUCCESS differs from comparison outcome']),
      ('DB','PostgreSQL',['Job, document, result, outbox and inbox','Owner revision + StreamEvent delivery ledger'],'PG','pgAdmin',[':5050 · lab_viewer','SELECT seven allowlisted application tables']),
      ('Cache','Two fixed Valkey shards',['Owner-channel wakes + socket lease keys','Transient fan-out; durable replay lives in SQL'],'CacheView','Redis Commander',[':8089 · viewer','Both shards; scoped read-only Valkey ACL']),
      ('Original','SeaweedFS originals',['Stored source bytes, including quarantine','Application scan/owner gates remain separate'],'StorageView','SeaweedFS admin',[':23646 · privileged read-only operator','Cluster-wide reads include raw originals']),
    ]
    for i,(left,lt,lb,right,rt,rb) in enumerate(rows):
        y=120+i*175
        d.node(left,32,y,460,135,lt,lb)
        d.node(right,568,y,460,135,rt,rb,tone='control')
        d.edge(right,left,[(568,y+68),(494,y+68)],wake=True)
    d.foot(1040,'OpenObserve :5080 correlates API, job/event relays, worker, provider and gateway metadata using job/request IDs.',
           'Stream metrics expose connection, replay queue and database-work bounds; source bytes and credentials stay out of logs.',
           'ClamAV terminal inspection: docker compose exec scanner clamdtop')
    d.save()


def support():
    d=Diagram('aws-support','AWS: controls beside the request path','Supporting relationships · not additional serial document-processing hops',
        'ECR and ECS/Fargate launch role-separated tasks. VPC, PrivateLink and security groups constrain private connections. IAM, Secrets Manager, KMS and ACM provide scoped identities and protection. CloudWatch observes logs, delivery metrics and bounded supply.',1215)
    rows=[
      ('Images','Launch: ECR',['Versioned image digests','Execution roles pull selected images'],'ecr','Compute','Run: ECS + Fargate',['App, workers and both relays','Independent raw ASGI gateway role'],'ecs','fargate'),
      ('Network','Connect: VPC',['Private task/data subnets + security groups','Only specified roles, peers and ports'],'vpc','Endpoints','PrivateLink + S3 endpoint',['ECR, secrets, logs and Bedrock privately','S3 gateway endpoint carries scoped source I/O'],'private','s3'),
      ('Roles','Authorize: IAM',['Separate task, execution and scanner roles','Only workers receive model invocation access'],'iam','Secrets','Configure: Secrets Manager',['Role-specific startup secret injection','App/stream proxy logins; direct bootstrap only'],'secrets',None),
      ('Keys','Protect: KMS',['S3, RDS, MQ, Valkey, secrets and logs','Selected role/service grants control access'],'kms','Trust','Endpoint: Route53 + ACM',['Route53 resolves ALB; ACM serves its certificate','Proxy and database use verified CA trust'],'dns','acm'),
      ('SQL','Bound SQL: RDS Proxy',['App DML role; gateway four-table reader','Nonlogin owner handles direct migrations'],'proxy','Metrics','Observe: CloudWatch',['Retained stdout + EMF ConnectedStreams','Queue age, proxy, fan-out and saturation alarms'],'logs',None),
    ]
    for i,(a,at,ab,ai,b,bt,bb,bi,bj) in enumerate(rows):
        y=120+i*195
        d.node(a,32,y,460,150,at,ab,(ai,))
        d.node(b,568,y,460,150,bt,bb,(bi,bj) if bj else (bi,))
    d.foot(1130,'Same architecture starts with small configurable replicas. Growth toward1m connected users /100 comparisons/s is planning.'.replace('toward1m','toward 1m').replace('/100','/ 100'),
           'Definitions and local checks do not establish deployed AWS behavior, quotas, model supply or target capacity.')
    d.save()


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.parse_args()
    overview()
    overview(True)
    event_delivery()
    aws_delivery()
    inspection()
    support()
    print('Wrote seven native SVG views and six matching logical companions; original AWS icon files unchanged.')


if __name__=='__main__':main()
