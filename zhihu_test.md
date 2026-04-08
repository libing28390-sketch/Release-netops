       做开源的相信都听过一些软路由的软件，例如quagga/zebra，今天我们来简单介绍下另一个开源路由软件：gobgp，从名字上就可以看出来，基于go开发的一款工具，性能自然是杠杠的了。此外，该工具仅支持BGP，并不像zerba那样，支持ospf，rip，bgp等其他路由协议。
看下官方介绍：GitHub - osrg/gobgp: BGP implemented in the Go Programming Language
GoBGP is an open source Border Gateway Protocol (BGP) implementation designed from scratch for modern environment and implemented in a modern programming language,the Go Programming Language.  
一、实验环境：
1.Red Hat Enterprise Linux Server release 7.1 (Maipo)   安装gobgp
2.EVE-NG模拟器，用来和server 之间建立bgp邻居
话不多说，我们直接上EVE-NG的拓扑图，server和三台思科IOL之间是通过cloud0桥接打通的，server并不在EVE里面，为了更好的展示整个拓扑，所以在图里添加了个server，方便大家理解。

添加图片注释，不超过 140 字（可选）
注意下，这里我的Net桥接到VMware的vmnet8 nat模式下，也可选择仅主机模式，保证和linux服务器在一个网段内即可。EVE-NG里拉一多云出来，type选择Management（Cloud0）

添加图片注释，不超过 140 字（可选）

二、实验需求
R3上可以收到R5的环回口地址的BGP路由，并且访问正常。
三、server以及路由器上相关配置
1、先在服务器上测试下互联地址：

添加图片注释，不超过 140 字（可选）
2、部署gobgp以及配置文件
 在server上安装gobgp，打开： https://github.com/osrg/gobgp/releases,选择对应的版本下载即可。

添加图片注释，不超过 140 字（可选）
  下载完成后，解压后可以看到 gobgp 以及gobgpd两个文件
 tar -zxf gobgp_3.10.0_linux_amd64.tar.gz
下面我们来创建bgp配置文件,官方介绍配置文件格式很多，json，yaml,  hcl都可以，这里使用的toml格式.
GoBGP can be configured via a configuration file or gRPC API. This example uses the following very simple configuration. All keys are case-insensitive. Default configuration format of GoBGP istoml. If you don't liketoml, you can usejson,yamlandhclinstead.
这里server当做RR，把路由反射给R1-R3，具体配置文件信息 gobgpd.conf
[global.config]
  as = 65001
  router-id = "192.168.48.140"

[[neighbors]]
  [neighbors.config]
    neighbor-address = "192.168.48.148"
    peer-as = 65001
  [neighbors.route-reflector.config]
    route-reflector-client = true
    route-reflector-cluster-id = "192.168.48.140"

[[neighbors]]
[neighbors.config]
  neighbor-address = "192.168.48.149"
  peer-as = 65001
  [neighbors.route-reflector.config]
    route-reflector-client = true
    route-reflector-cluster-id = "192.168.48.140"

[[neighbors]]
  [neighbors.config]
    neighbor-address = "192.168.48.150"
    peer-as = 65001
  [neighbors.route-reflector.config]
    route-reflector-client = true
    route-reflector-cluster-id = "192.168.48.140"


#转成在路由器上的配置，以思科设备为例：
router bgp 65001
 bgp router-id 192.168.48.140
 bgp log-neighbor-changes
 neighbor 192.168.48.148 remote-as 65001
 neighbor 192.168.48.149 remote-as 65001
 neighbor 192.168.48.150 remote-as 65001
 !
 address-family ipv4
  neighbor 192.168.48.148 activate
  neighbor 192.168.48.148 route-reflector-client
  neighbor 192.168.48.149 activate
  neighbor 192.168.48.149 route-reflector-client
  neighbor 192.168.48.150 activate
  neighbor 192.168.48.150 route-reflector-client
3、路由器上相关配置：
R1、R2、R3和server之间建立IBGP邻居，R1和R5之间建立EBGP邻居
interface Loopback0
 ip address 172.16.1.1 255.255.255.255
!
interface Ethernet0/0
 ip address 192.168.48.149 255.255.255.0
 duplex auto
!
interface Ethernet0/1
 ip address 10.1.1.1 255.255.255.0
 duplex auto
!
interface Ethernet0/2
 no ip address
 shutdown 
 duplex auto
!         
interface Ethernet0/3
 no ip address
 shutdown 
 duplex auto
!         
router bgp 65001
 bgp router-id 172.16.1.1
 bgp log-neighbor-changes
 neighbor 10.1.1.5 remote-as 65002
 neighbor 192.168.48.140 remote-as 65001
 !
 address-family ipv4
  network 10.1.1.0 mask 255.255.255.0
  network 172.16.1.1 mask 255.255.255.255
  neighbor 10.1.1.5 activate
  neighbor 192.168.48.140 activate
 exit-address-family
R5配置：
interface Loopback0
 ip address 5.5.5.5 255.255.255.255
!
interface Ethernet0/0
 no ip address
 duplex auto
!
interface Ethernet0/1
 ip address 10.1.1.5 255.255.255.0
 duplex auto
!
interface Ethernet0/2
 no ip address
 shutdown
 duplex auto
!
interface Ethernet0/3
 no ip address
 shutdown
 duplex auto
!
router bgp 65002
 bgp router-id 5.5.5.5
 bgp log-neighbor-changes
 neighbor 10.1.1.1 remote-as 65001
 !
 address-family ipv4
  network 5.5.5.5 mask 255.255.255.255
  redistribute connected
  neighbor 10.1.1.1 activate
 exit-address-family
4、启动gobgp，建立bgp邻居同时可以看到相关的日志，显示三个邻居均UP状态
./gobgpd -f gobgpd.conf 
[root@server ~]# ./start_bgp.sh
{"level":"info","msg":"gobgpd started","time":"2023-01-07T21:25:40+08:00"}
{"Topic":"Config","level":"info","msg":"Finished reading the config file","time":"2023-01-07T21:25:40+08:00"}
{"Key":"192.168.48.148","Topic":"config","level":"info","msg":"Add Peer","time":"2023-01-07T21:25:40+08:00"}
{"Key":"192.168.48.148","Topic":"Peer","level":"info","msg":"Add a peer configuration","time":"2023-01-07T21:25:40+08:00"}
{"Key":"192.168.48.149","Topic":"config","level":"info","msg":"Add Peer","time":"2023-01-07T21:25:40+08:00"}
{"Key":"192.168.48.149","Topic":"Peer","level":"info","msg":"Add a peer configuration","time":"2023-01-07T21:25:40+08:00"}
{"Key":"192.168.48.150","Topic":"config","level":"info","msg":"Add Peer","time":"2023-01-07T21:25:40+08:00"}
{"Key":"192.168.48.150","Topic":"Peer","level":"info","msg":"Add a peer configuration","time":"2023-01-07T21:25:40+08:00"}
gobgp is starting,please wait....
[root@server ~]# {"Key":"192.168.48.150","State":"BGP_FSM_OPENCONFIRM","Topic":"Peer","level":"info","msg":"Peer Up","time":"2023-01-07T21:25:46+08:00"}
{"Key":"192.168.48.149","State":"BGP_FSM_OPENCONFIRM","Topic":"Peer","level":"info","msg":"Peer Up","time":"2023-01-07T21:25:47+08:00"}
{"Key":"192.168.48.148","State":"BGP_FSM_OPENCONFIRM","Topic":"Peer","level":"info","msg":"Peer Up","time":"2023-01-07T21:25:48+08:00"}

这里为了后续方便测试，我编写了三个简单的脚本
[root@server ~]# cat start_bgp.sh
#!/bin/bash
pro_check=`ps -ef| grep gobgp|grep -v grep|wc -l`
if [ $pro_check=1 ];then
./gobgpd -f gobgpd.conf &
sleep 3
./gobgp global rib add 192.168.48.0/24 -a ipv4
echo "**********gobgp is starting,please wait....**********"
fi
[root@server ~]# cat restart_bgp.sh
#!/bin/bash
pro_check=`ps -ef| grep gobgp|grep -v grep|wc -l`
if [ $pro_check=1 ];then
echo "gobgp process has start"
fi
gobgp_pid=`ps -ef| grep gobgp| grep -v grep | awk '{print$2}'`
echo $gobgp_pid
kill -9 $gobgp_pid
echo "********** restart gobgp *********"
./start_bgp.sh
[root@server ~]# cat stop_bgp.sh
#!/bin/bash
gobgp_pid=`ps -ef| grep gobgp| grep -v grep | awk '{print$2}'`
kill -9 $gobgp_pid

num_process=`ps -ef| grep gobgp|wc -l`
if [ $num_process=1 ];then
echo '***********gobgp has stoped***********'
fi

5、检查下gobgp启动是否正常，可以判断TCP 179端口监听是否正常
[root@server ~]# ss -antlp| grep -w 179

添加图片注释，不超过 140 字（可选）
6、检查bgp邻居状态:
[root@server ~]# ./gobgp neighbor

添加图片注释，不超过 140 字（可选）
查看指定邻居详细信息：

添加图片注释，不超过 140 字（可选）
7、查看bgp路由表:

添加图片注释，不超过 140 字（可选）
上图中，我们是可以看到server在bgp中宣告了这条路由，
start_bgp.sh 脚本里我们添加了这个路由

./gobgp global rib add 192.168.1.0/24 -a ipv4,
8、同时，我们也可以看看server和邻居之间的收发路由情况，以R1为例：
R1#sh bgp ipv4 unicast neighbors 192.168.48.140 routes 
BGP table version is 46, local router ID is 172.16.1.1
Status codes: s suppressed, d damped, h history, * valid, > best, i - internal, 
              r RIB-failure, S Stale, m multipath, b backup-path, f RT-Filter, 
              x best-external, a additional-path, c RIB-compressed, 
              t secondary path, 
Origin codes: i - IGP, e - EGP, ? - incomplete
RPKI validation codes: V valid, I invalid, N Not found

     Network          Next Hop            Metric LocPrf Weight Path
 *>i  172.16.1.2/32    192.168.48.148           0    100      0 i
 *>i  172.16.1.3/32    192.168.48.150           0    100      0 i
 r>i  192.168.48.0     192.168.48.140                100      0 ?

Total number of prefixes 3 
R1#
R1#
R1#sh bgp ipv4 unicast neighbors 192.168.48.140 advertised-routes      
BGP table version is 46, local router ID is 172.16.1.1
Status codes: s suppressed, d damped, h history, * valid, > best, i - internal, 
              r RIB-failure, S Stale, m multipath, b backup-path, f RT-Filter, 
              x best-external, a additional-path, c RIB-compressed, 
              t secondary path, 
Origin codes: i - IGP, e - EGP, ? - incomplete
RPKI validation codes: V valid, I invalid, N Not found

     Network          Next Hop            Metric LocPrf Weight Path
 *>   5.5.5.5/32       10.1.1.5                 0             0 65002 i
 *>   10.1.1.0/24      0.0.0.0                  0         32768 i
 *>   172.16.1.1/32    0.0.0.0                  0         32768 i

然后在server上查看下路由表
[root@server ~]# ./gobgp neighbor 192.168.48.149 adj-in
   ID  Network              Next Hop             AS_PATH              Age        Attrs
   0   5.5.5.5/32           10.1.1.5             65002                00:39:48   [{Origin: i} {Med: 0} {LocalPref: 100}]
   0   10.1.1.0/24          192.168.48.149                            00:39:48   [{Origin: i} {Med: 0} {LocalPref: 100}]
   0   172.16.1.1/32        192.168.48.149                            00:39:48   [{Origin: i} {Med: 0} {LocalPref: 100}]
[root@server ~]#
[root@server ~]#
[root@server ~]# ./gobgp neighbor 192.168.48.149 adj-out
   ID  Network              Next Hop             AS_PATH              Attrs
   1   172.16.1.2/32        192.168.48.148                            [{Origin: i} {Med: 0} {LocalPref: 100} {Originator: 172.16.1.2} {ClusterList: [192.168.48.140]}]
   1   172.16.1.3/32        192.168.48.150                            [{Origin: i} {Med: 0} {LocalPref: 100} {Originator: 172.16.1.3} {ClusterList: [192.168.48.140]}]
   1   192.168.48.0/24      192.168.48.140                            [{Origin: ?} {LocalPref: 100} {Originator: 192.168.48.140} {ClusterList: [192.168.48.140]}]

9、路由器上分别验证bgp邻居以及路由：R1-R3,R5
R1:

添加图片注释，不超过 140 字（可选）
R2:

添加图片注释，不超过 140 字（可选）
R3:

添加图片注释，不超过 140 字（可选）
R5:

添加图片注释，不超过 140 字（可选）
四、R3、R5上验证结果：
这里我们可以看到R3上的cluster list ID为server的RID，证实5.5.5.5这条路由是从RR上学过来的
R3#traceroute 5.5.5.5 source loopback 0 numeric 
Type escape sequence to abort.
Tracing the route to 5.5.5.5
VRF info: (vrf in name/id, vrf out name/id)
  1 192.168.48.149 0 msec 0 msec 0 msec
  2 10.1.1.5 0 msec *  1 msec

R3#sh bgp ipv4 unicast 5.5.5.5   
BGP routing table entry for 5.5.5.5/32, version 60
Paths: (1 available, best #1, table default)
  Not advertised to any peer
  Refresh Epoch 1
  65002
    10.1.1.5 from 192.168.48.140 (192.168.48.140)
      Origin IGP, metric 0, localpref 100, valid, internal, best
      Originator: 172.16.1.1, Cluster list: 192.168.48.140
      rx pathid: 0, tx pathid: 0x0


---------------------------------------------

R5#sh bgp ipv4 unicast 172.16.1.3
BGP routing table entry for 172.16.1.3/32, version 43
Paths: (1 available, best #1, table default)
  Not advertised to any peer
  Refresh Epoch 1
  65001
    10.1.1.1 from 10.1.1.1 (172.16.1.1)
      Origin IGP, localpref 100, valid, external, best
      rx pathid: 0, tx pathid: 0x0

R5#traceroute 172.16.1.3 source loopback 0 numeric 
Type escape sequence to abort.
Tracing the route to 172.16.1.3
VRF info: (vrf in name/id, vrf out name/id)
  1 10.1.1.1 0 msec 0 msec 0 msec
  2 192.168.48.150 [AS 65001] 0 msec *  1 msec
五、实验总结
    实验过程中遇到很多坑，给大家总结下，使用vmware nat网卡做桥接时，路由器的接口最好是手动配置。另外测试的环回口地址最好是使用一些不常见的地址，我在server上测试1.1.1.1 以及10.10.10.10 这两地址都直接走公网出去了，给我耽误了不少时间。
  下一期，我们来玩玩bgp的更多高级特性，例如vrf，route-policy, 看看gobgp是如何做到的