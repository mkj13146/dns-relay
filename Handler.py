import socket
import os
from dns import message
from DBFacade import DBFacade
from MyLog import logger

class Handler:
    def __init__(self, c_addr, data, c_socket, send_ip, send_port, timeout_time = 3):
        self.c_addr = c_addr
        self.c_data = data
        self.c_socket = c_socket
        self.send_ip = send_ip
        self.send_port = send_port
        self.timeout_time = timeout_time
        self.process_pac = True
       
    def run(self):
        flag = False        #判定数据库中是否检索到所需条目
        # 利用python message库解析
        if self.process_pac:
            data_dic = self.data_process(self.c_data)
            _name , _type = data_dic['QUESTION'][0][0],data_dic['QUESTION'][0][2]   #原始请求
        # 利用自程序解析
        else:
             #管道处理：
            data_get = self.data_process_c(self.pip_creat(self.c_data))
            _name , _type = data_get[0],data_get[1]
        #查询数据库
        db = DBFacade()
        answer = db.query(_name , _type)
        flag = (answer == [])

        if flag == False:    #用数据库查到的数据向客户端发送   

            remark = 'Local'
            if answer[0][4] == '0.0.0.0' or answer[0][4] == '0:0:0:0:0:0:0:0':           #拦截不良网站
                print('拦截不良网站：', _name)
                remark = 'Rejected'

            elif answer[0][3] == 'MX':                                #answer 的处理 （MX）
                for i in range(len(answer)):
                    answer[i].insert(4,'5')       
                                           
            temp_message = message.from_wire(self.c_data)
            temp_message = message.make_response(temp_message).to_text()
            temp_list = temp_message.split("\n")
            index = temp_list.index(";ANSWER")
            for ret in answer:
                temp_list.insert(index+1,' '.join(ret))
                index += 1
            if remark == 'Rejected':    #不良网站处理，标志位rcode 设为nxdomain
                temp_list[2] = 'rcode NXDOMAIN';

            data_send = '\n'.join(temp_list)
            data_send = message.from_text(data_send)
            data_send = data_send.to_wire()
            self.c_socket.sendto(data_send, self.c_addr)     #向客户端发回
            
          
        else:       #请求DNS服务器
            self.s_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)  # 与DNS服务器通信的套接字
            self.s_socket.sendto(self.c_data, (self.send_ip, self.send_port))      #向服务器发送
            self.s_socket.settimeout(self.timeout_time)         #设置超时时间

            try:
                data, addr = self.s_socket.recvfrom(1024)     #读回DNS服务器的返回
                remark = 'Remote'
              
                if self.process_pac:
                    #利用python  message库处理
                    data_dic = self.data_process(data)
                    # 存数据库  data_dic['ANSWER']
                    db = DBFacade()
                    db.insert_records(data_dic["ANSWER"])
                else:
                    #利用自程序处理
                    data_get = self.data_process_s(self.pip_creat(data))
                    if data_get[0][0] != "null":
                        db = DBFacade()
                        db.insert_records(data_get)
                #发回到客户端
                self.c_socket.sendto(data, self.c_addr)

            except socket.timeout:                            #DNS超时
                print('请求超时：', _name)
                remark = 'TimeOut'

            self.s_socket.close()       #获取DNS的返回后（或超时）关闭与服务器通信的socket
        
        #handler做完了一项工作，插入日志，退出
        logger.info('%s:%s      %s      %s      %s'%(self.c_addr[0], self.c_addr[1], _name , _type, remark))
            

    def data_process(self,data_get):
        data_message = message.from_wire(data_get).to_text()
        data_list = data_message.split('\n')
        data_dic = {}
        Question = []
        Answer = []
        data_dic['id'] = data_list[0][2:]
        for index in range(len(data_list)):
            if index > data_list.index(';QUESTION') and index < data_list.index(';ANSWER'): #question
                data_temp = data_list[index].split(' ')
                Question.append(data_temp)
                    #
                    # question : name,class,type    for example: www.baidu.com.   IN   A
                    #
            elif index > data_list.index(';ANSWER') and index < data_list.index(';AUTHORITY'): #answer
                data_temp = data_list[index].split(' ')
                if data_temp[3] == 'MX':            #对于MX类型  省略优先级
                    data_temp.remove(data_temp[4])
                Answer.append(data_temp)
                    #
                    # answer : name,ttl,class,type,value    for example :www.baidu.com.   168 IN A 39.156.66.18
                    #
        data_dic['QUESTION'] = Question
        data_dic['ANSWER'] = Answer
        return data_dic


    def data_process_c(self,data_get):
        ret_list = data_get.decode().split("=>")
        if ret_list[1] == '1':
            ret_list[1] = 'A'
        elif ret_list[1] == '15':
            ret_list[1] = 'MX'
        elif ret_list[1] == '5':
            ret_list[1] = 'CNAME'
        ###print(ret_list)
        return ret_list
    def data_process_s(self,data_get):
        temp_list = data_get.decode().split("\n")
        ret_list = []
        for record in temp_list:
            temp2_list = record.split('----')
            ret_list.append(temp2_list)
        ###print(ret_list)
        return ret_list


    def pip_creat(self,data):
        r , w = os.pipe()
        r2,w2 = os.pipe()
        pid = os.fork()
        #print ("write pipe len: " ,len(data))
        
        if pid == 0:
            os.write(w2, data)
            os.close(r)
            os.close(w2)
            os.dup2(w, 1)
            os.dup2(r2, 0)
            os.execl("parse" , "parse" )#exit
        else:
            os.wait()
            os.close(w)
            os.close(r2)
            ret = os.read(r, 2048)
            #print ("begin parse packet ",ret, " end")     #!ret接收到的字符  包含name 类型 类型1A   5cname  15MX
        os.close(w2)
        os.close(r)
        return ret
