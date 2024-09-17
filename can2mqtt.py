#!/usr/bin/python
"""
sudo modprobe vcan
sudo ip link add dev vcan0 type vcan
sudo ip link set vcan0 up
cansend vcan0 123#DEADBEEF0000
"""
from __future__ import print_function
import datetime
import argparse
import time
import socket
import sys
from threading import Event, Thread

import struct
import parse
import jsoncfg
import logging

import can
import paho.mqtt.client as mqtt

import can2mqtt_vias as vias

class RepeatedTimer:
    """Repeat `function` every `interval` seconds."""
    def __init__(self, interval, function, *args, **kwargs):
        self.interval = interval
        self.function = function
        self.args = args
        self.kwargs = kwargs
        self.start = time.time()
        self.event = Event()
        self.thread = Thread(target=self._target)
        self.thread.start()

    def _target(self):
        while not self.event.wait(self._time):
            self.function(*self.args, **self.kwargs)

    @property
    def _time(self):
        return self.interval - ((time.time() - self.start) % self.interval)

    def stop(self):
        self.event.set()
        self.thread.join()

def sync_master(bus, count):
    if count!=0:
        if not hasattr(sync_master, "counter"):
            sync_master.counter = 0
        else:
            sync_master.counter += 1
        if sync_master.counter >= count:
            sync_master.counter = 0
        data= [sync_master.counter]
    else:
        data= []
    bus.send(can.Message(extended_id= False, arbitration_id= 0x080, data= data))

def do_nmt_auto_start(m, bus):
    if (m.arbitration_id & ~0x7F)==0x700:
        device_id = m.arbitration_id & 0x7F
        if len(m.data)>0 and m.data[0]!=5:
            msg = bytearray([1, device_id])
            bus.send(can.Message(extended_id= False, arbitration_id= 0x000, data= msg))
    
   
def on_message(client, userdata, message):
    CANBus= userdata[0]
    transmitters= userdata[1]
    for sub in filter(lambda sub: mqtt.topic_matches_sub(sub, message.topic), transmitters.keys()):
        tmtrs= transmitters[sub]
        for tmtr in tmtrs:
            try:
                canid, data= tmtr.translate(message.topic, message.payload)
            except BaseException as e:
                logging.error("Error translating mqtt message \"%s\" from topic \"%s\" via transmitter %s: %s" % (message.payload, message.topic, tmtr.name, e))
                tmtr.error_count+= 1
                if tmtr.error_count >= 10:
                    logging.warning("Too many relaying errors via transmitter %s. Removing this transmitter" % tmtr.name)
                    transmitters[sub].remove(tmtr)
                continue
            
            try:
                m= can.Message(extended_id= False, arbitration_id= canid, data= data)
            except BaseException as e:
                logging.error("Error forming can message id= \"%s\", data \"%s\" via transmitter %s: %s" % (canid, data, tmtr.name, e))
                tmtr.error_count+= 1
                if tmtr.error_count >= 10:
                    logging.warning("Too many relaying errors via transmitter %s. Removing this transmitter" % tmtr.name)
                    transmitters[sub].remove(tmtr)
                continue
            try:
                CANBus.send(m)
            except BaseException as e:
                logging.error("Error sending can message {%s}: %s" % (m, e))
                        

def testForStringList(l, n):
    if not isinstance(l, list):
        l= [l]
    for e in l:
        if not isinstance(e, str):
            raise ValueError("All elements of parameter %s must be strings" % n)
    return l

class CanMessage2MQTT:
    def __init__(self, name, unpack_template, var_names, topic_template, payload_template):
        self.name= name
        
        if not isinstance(unpack_template, str):
            raise ValueError("Parameter unpack_template must be a string")
        self.unpack_template= unpack_template
        self.var_names= testForStringList(var_names, "var_names")
        self.var_vias= []
        for i, v in enumerate(self.var_names):
            r = v.split(" via ")
            if len(r)>1:
                self.var_names[i]= r[0]
                self.var_vias.append(r[1])
            else:
                self.var_vias.append(None)
                    
        self.topic_template= testForStringList(topic_template, "topic_template")
        self.payload_template= testForStringList(payload_template, "payload_template")
        self.error_count= 0
        
        
    def translate(self, m):
        data= dict()
        data['canid']= m.arbitration_id
        data['t']= m.timestamp
        data['dt']= datetime.datetime.fromtimestamp(m.timestamp)
        candata= m.data
        try:
            vals= struct.unpack(self.unpack_template, candata)
        except BaseException as e:
            raise ValueError("Error unpacking can data: %s" % e)
        try:
            mdata= dict(zip(self.var_names, vals))
        except BaseException as e:
            raise ValueError("Error assigning data to values: %s" % e)
        try:
            for i, v in enumerate(self.var_vias):
                if v:
                    mdata[self.var_names[i]]= eval("vias."+v+"(mdata[\""+self.var_names[i]+"\"])")
        except BaseException as e:
            raise ValueError("Error applying via \"%s\" to value \"%s\"= \"%s\": %s" % (v, self.var_names[i], mdata[self.var_names[i]], e))
                   
        data.update(mdata)
        
        for t, p in zip(self.topic_template, self.payload_template):
            try:
                topic= t.format(**data)
            except BaseException as e:
                raise ValueError("Error formating topic string \"%s\": %s" % (t, e))
            try:
                payload= p.format(**data)
            except BaseException as e:
                raise ValueError("Error formating payload string \"%s\": %s" % (p, e))
            
            yield topic, payload
    
    
class MQTT2CanMessage:
    def __init__(self, name, canid, subscriptions, pack_template, var_names, topic_template, payload_template):
        self.name= name
        
        if not isinstance(canid, str) and not isinstance(canid, int):
            raise ValueError("Parameter canid must be a string or an int")
        if isinstance(canid, str):
            try:
                canid= int(canid, 0)
            except:
                pass
            
        self.subscriptions= testForStringList(subscriptions, "subscriptions")
        
        if not isinstance(pack_template, str):
            raise ValueError("Parameter pack_template must be a string")
        self.canid= canid
        self.pack_template= pack_template
        self.var_names= testForStringList(var_names, "var_names")

        if topic_template:
            if not isinstance(topic_template, str):
                raise ValueError("Parameter topic_template must be a string")
            try:
                self.topic_template= parse.compile(topic_template)
            except BaseException as e:
                raise ValueError("Error compiling topic_template: %s" % e)
        else:
            self.topic_template= None
            
        if not isinstance(payload_template, str):
            raise ValueError("Parameter payload_template must be a string")
        try:
            self.payload_template= parse.compile(payload_template)
        except BaseException as e:
            raise ValueError("Error compiling payload_template: %s" % e)
        
        self.error_count= 0
        
        
    def translate(self, topic, payload):
        vd= dict()
        
        if self.topic_template:
            try:
                topic_vals= self.topic_template.search(topic)
                vd.update(topic_vals.named)
            except BaseException as e:
                raise ValueError("Error parsing topic \"%s\": %s" % (topic, e))
            
        try:
            payload_vals= self.payload_template.search(payload)
            vd.update(payload_vals.named)
        except BaseException as e:
            raise ValueError("Error parsing payload \"%s\": %s" % (payload, e))
        
        if isinstance(self.canid, int):
            canid= self.canid
        else:
            try:
                if isinstance(vd[self.canid], int):
                    canid= vd[self.canid]
                else:
                    canid= int(vd[self.canid], 0)
            except BaseException as e:
                raise ValueError("Error forming can id from value \"%s\": %s" % (self.canid, e))
        
        try:
            vals= [vd[v] for v in self.var_names]
        except BaseException as e:
            raise ValueError("Error collecting values: %s" % e)
        
        try:
            data= struct.pack(self.pack_template, *vals)
        except BaseException as e:
            raise ValueError("Error packing can data: %s" % e)
            
        return canid, data

def main():
    parser = argparse.ArgumentParser(description="Bridge messages between CAN bus and MQTT server")

    parser.add_argument("-c", "--config_name", dest="config_file",
                        help="""Path and name of configuration file""",
                        default="config.json")

    parser.add_argument('-l', '--log_file', dest="log_file", help='''Path and name of log file''', default= None)

    parser.add_argument("-v", dest="verbosity", help='''Log level''', default="INFO", choices= ["CRITICAL", "ERROR", "WARNING", "INFO", "DEBUG", "NOTSET"])

    args = parser.parse_args()

    numeric_level = getattr(logging, args.verbosity, None)
    if args.log_file:
        logging.basicConfig(level=numeric_level, filename=args.log_file, filemode='w', format='%(asctime)s %(levelname)s:%(message)s')
    else:
        logging.basicConfig(level=numeric_level, format='%(asctime)s %(levelname)s:%(message)s')
    
    logging.info("Reading configuration")
    try:
        c = jsoncfg.load_config(args.config_file)
    except BaseException as e:
        logging.error("Error reading config file: %s" % e)
        sys.exit(1)
    
    receivers= dict()
    if jsoncfg.node_exists(c.receivers):
        logging.info("Loading receivers")
        rcvrs= c.receivers
        for i, r in enumerate(jsoncfg.expect_array(rcvrs)):
            name= r.name("receiver_"+str(i))
            try:
                rcvr= CanMessage2MQTT(name, r.unpack_template(), r.var_names(), r.topic_template(), r.payload_template())
                canid= r.canid()
            except jsoncfg.JSONConfigValueNotFoundError as e:
                logging.error("Could not load receiver %s (#%d). Parameter \"%s\" not found at line= %d, col= %d" % (name, i+1, e.relative_path, e.line, e.column))
                continue
            except ValueError as e:
                logging.error("Could not load receiver %s (#%d): %s" % (name, i+1, e))
                continue
                
            
            if not isinstance(canid, list):
                canids= [canid]
            for canid in canids:
                if isinstance(canid, str):
                    try:
                        canid= int(canid, 0)
                    except ValueError as e:
                        logging.error("Could not add receiver %s (#%d) to listen to can id: %s" % (name, i+1, e.message))
                        continue
                elif not isinstance(canid, int):
                    logging.error("Could not add receiver %s (#%d) to listen to can id %s because it is neither string nor int" % (name, i+1, str(canid)))
                    continue
                receivers[canid]= rcvr
    
    transmitters= dict()
    if jsoncfg.node_exists(c.transmitters):
        logging.info("Loading transmitters")
        tmtrs= c.transmitters
        for i, t in enumerate(jsoncfg.expect_array(tmtrs)):
            name= t.name("transmitter_"+str(i))
            try:
                tmtr= MQTT2CanMessage(name, t.canid(), t.subscriptions(), t.pack_template(), t.var_names(), t.topic_template(None), t.payload_template())
            except jsoncfg.JSONConfigValueNotFoundError as e:
                logging.error("Could not load transmitter %s (#%d). Parameter \"%s\" not found at line= %d, col= %d" % (name, i+1, e.relative_path, e.line, e.column))
                continue
            except ValueError as e:
                logging.error("Could not load transmitter %s (#%d): %s" % (name, i+1, e))
                continue
                
            for s in tmtr.subscriptions:
                if s in transmitters:
                    transmitters[s].append(tmtr)
                else:
                    transmitters[s]= [tmtr]
    
    logging.info("Starting CAN bus")
    if not jsoncfg.node_exists(c.canbus.interface):
        logging.error("No can interface specified. Valid interfaces are: %s" % can.interface.VALID_INTERFACES)
        sys.exit(1)
        
    try:
        bus = can.interface.Bus(c.canbus.channel(), bustype=c.canbus.interface())
        canBuffer= can.BufferedReader()
        notifier = can.Notifier(bus, [canBuffer], timeout=0.1)
    except BaseException as e:
        logging.error("CAN bus error: %s" % e)
        sys.exit(1)
    
    logging.info("Starting MQTT")
    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION1,client_id=c.mqtt.client_id("can2mqtt"), protocol=mqtt.MQTTv31)
    client.on_message= on_message
    client.user_data_set((bus, transmitters))
    try:
        mqtt_errno= client.connect(c.mqtt.host("127.0.0.1"), c.mqtt.port(1883), 60)
        if mqtt_errno!=0:
            raise Exception(error_string(mqtt_errno))
                            
        client.loop_start()
    except BaseException as e:
        logging.error("MQTT error: %s" % e)
        bus.shutdown()
        notifier.stop()
        sys.exit(1)
        
        
    logging.info("Adding MQTT subscriptions")
    for s in transmitters:
        try:
            # message_callback_add()
            client.subscribe(s)
        except BaseException as e:
            logging.error("Error adding subscribtion \"%s\": %s" % (s, e))

    if jsoncfg.node_exists(c.canopen.sync_interval):
        logging.info("Adding CANopen sync master")
        sync_interval= c.canopen.sync_interval()
        if isinstance(sync_interval, int):
            sync_interval= float(sync_interval)
        if isinstance(sync_interval, float):
            if jsoncfg.node_exists(c.canopen.sync_count):
                sync_count= c.canopen.sync_count()
            else:
                sync_count= 0
            if not isinstance(sync_count, int):
                logging.warning("Parameter sync_count is not an int. Using 0")
                sync_count= 0
            sync_timer = RepeatedTimer(sync_interval, sync_master, bus, sync_count)
        else:
            logging.warning("Parameter sync_interval must be int or float. Sync master not activated")
            sync_timer= None
    else:
        sync_timer= None

    if jsoncfg.node_exists(c.canopen.auto_start):
        nmt_auto_start = c.canopen.auto_start()
        if not isinstance(nmt_auto_start, bool):
            logging.warning("Parmeter canopen.auto_start must be boolean. Auto start not activated")
            nmt_auto_start = False
    else:
        nmt_auto_start = False
            
        
    logging.info("Starting main loop")
    try:
        while True:
            # test delay for stress test
            # time.sleep(0.005)
            m= canBuffer.get_message()
            if m is not None:
                if nmt_auto_start:
                    do_nmt_auto_start(m, bus)

                if m.arbitration_id in receivers:
                    rcvr= receivers[m.arbitration_id]
                    try:
                        for t, p in rcvr.translate(m):
                            r= client.publish(t, p)
                            if not (r[0] == mqtt.MQTT_ERR_SUCCESS):
                                logging.error("Error publishing message \"%s\" to topic \"%s\". Return code %s: %s" % (t, p, str(r[0]), mqtt.error_string(r[0])))
                    except BaseException as e:
                        logging.error("Error relaying message {%s} via receiver %s: %s" % (m, rcvr.name, e))
                        rcvr.error_count+= 1
                        if rcvr.error_count >= 10:
                            logging.warning("Too many relaying errors via receiver %s. Removing this receiver" % rcvr.name)
                            del receivers[m.arbitration_id]
                
                
    except KeyboardInterrupt:
        bus.shutdown()
        notifier.stop()
        client.loop_stop()
        client.disconnect()
        if sync_timer:
            sync_timer.stop()

if __name__ == "__main__":
    main()
