import time
import re
import os
import csv
from netmiko.cisco_base_connection import CiscoSSHConnection
from netmiko import log
import textfsm
import argparse
from datetime import datetime
from influxdb import InfluxDBClient
from influxdb import SeriesHelper


dccap = []
dccap_cm = {}
olt_list = {}


parser = argparse.ArgumentParser(description='Poll parameters from OLT')
parser.add_argument('--ip', dest='ip_address', default="",
                    help='Hostname or IP Address')
parser.add_argument('--olt', dest='olt_name',
                    default="", help='Name of the OLT')
parser.add_argument('--olt_file', dest='olt_file_name', default="",
                    help='File with the list of olts in csv format oltname,IP')
parser.add_argument('--ssh_user', dest='ssh_user',
                    default='rfalla', help='SSH user to connect to OLT')
parser.add_argument('--ssh_pwd', dest='ssh_pwd', default='rfalla214',
                    help='SSH users password to connect to OLT')
parser.add_argument('--community', dest='community',
                    default='u2000_ro', help='SNMP read community')
parser.add_argument('--per_channel_bw', dest='per_channel_bw',
                    default=False, help='True if you want traffic per channel')
parser.add_argument('--out_influxdb', dest='out_influxdb',
                    default=False, help='True if you want to send to influxdb')

args = parser.parse_args()

myclient = InfluxDBClient('localhost', 8086, 'root', 'root', 'telegraf')


class DCCAPSeriesHelper(SeriesHelper):
    """Instantiate SeriesHelper to write points to the backend."""

    class Meta:
        """Meta class stores time series helper configuration."""

        # The client should be an instance of InfluxDBClient.
        client = myclient

        # The series name must be a string. Add dependent fields/tags
        # in curly brackets.
        series_name = 'claro_dccap'

        # Defines all the fields in this time series.
        fields = ['gpon_port', 'interface_cable', 'cm_total', 'cm_online', 'cm_offline', 'downstream_traffic',
            'upstream_traffic', 'total_d30_down', 'total_d30_up', 'total_d31_down', 'total_d31_up']
        # Defines all the tags for the series.
        tags = ['olt_name', 'alias_name']
        # Defines the number of data points to store prior to writing
        # on the wire.
        bulk_size = 20

        # autocommit must be set to True when using bulk_size
        autocommit = True


class OLTSeriesHelper(SeriesHelper):
    """Instantiate SeriesHelper to write points to the backend."""

    class Meta:
        """Meta class stores time series helper configuration."""

        # The client should be an instance of InfluxDBClient.
        client = myclient

        # The series name must be a string. Add dependent fields/tags
        # in curly brackets.
        series_name = 'claro_olt_dccap'

        # Defines all the fields in this time series.
        fields = ['total_dccaps', 'total_cm', 'total_cm_online',
            'total_cm_offline', 'total_dccap_downlink', 'total_dccap_uplink']
        # Defines all the tags for the series.
        tags = ['olt_name']
        # Defines the number of data points to store prior to writing
        # on the wire.
        bulk_size = 20

        # autocommit must be set to True when using bulk_size
        autocommit = True


class OLT():
        def __init__(self, name, ip, total_dccaps=0, total_cm=0, total_cm_online=0, total_cm_offline=0, olt_uplink=0, olt_downlink=0):
                self.name = name
                self.ip = ip
                self.total_dccaps = total_dccaps
                self.total_cm = total_cm
                self.total_cm_online = total_cm_online
                self.total_cm_offline = total_cm_offline
                self.uplink = olt_uplink
                self.downlink = olt_downlink

        def update_influx_db(self):
                OLTSeriesHelper(olt_name=self.name, total_dccaps=self.total_dccaps, total_cm=self.total_cm, total_cm_online=self.total_cm_online,
                                total_cm_offline=self.total_cm_offline, total_dccap_downlink=self.downlink, total_dccap_uplink=self.uplink)


class Docsis_Channel():
	def __init__(self, name, type_docsis, utilization, real_traffic, max_traffic):
		self.name = name
		self.type_docsis = type_docsis
		#self.cable_modems = 0
		self.utilization = utilization
		self.real_traffic = real_traffic
		self.max_traffic = max_traffic

	def print_summary(self):
		str_list = []
		str_list.append(self.name)
		str_list.append(self.type_docsis)
		str_list.append(str(self.utilization))
		str_list.append(str(self.real_traffic))
		str_list.append(str(self.max_traffic))
		return str_list


class DCCAP_modems_summary():
    def __init__(self, Total, Online, Offline):
        self.total = Total
        self.online = Online
        self.offline = Offline


class DCCAP():
	def __init__(self, olt_name, olt_gpon_port, interface_cable, alias_name, serial, status):
	    self.olt_name = olt_name
        self.interface_cable = interface_cable
		self.alias_name = alias_name
		self.gpon_port = olt_gpon_port
		self.serial = serial
		self.status = status
		self.channels = []
        self.cable_modem_summary = None

    def update_influx_db(self):
        (dccap_downstream,dccap_upstream)=self.get_total_bandwidth()
        DCCAPSeriesHelper(olt_name=self.olt_name,alias_name=self.alias_name,gpon_port=self.gpon_port,interface_cable=self.interface_cable,
						  cm_total=self.cable_modem_summary.total,cm_online=self.cable_modem_summary.online,cm_offline=self.cable_modem_summary.offline,
						  downstream_traffic=dccap_downstream,upstream_traffic=dccap_upstream,total_d30_down=self.get_d30_down(),total_d30_up=self.get_d30_up(),total_d31_down=self.get_d31_down(),total_d31_up=self.get_d31_up())
	
	def print_channel_summary(self):
		print("channel,type_docsis,channel_utilization,real_traffic,max_traffic")
		for current_channel in self.channels:
			print(",".join(current_channel.print_summary()))
    
	def get_total_bandwidth(self):
                downstream = 0
                upstream = 0
                for channel in self.channels:
                    is_upstream = channel.name[0]=='U'
                    is_downstream = channel.name[0]=='D'
                    if is_upstream:
                        upstream += channel.real_traffic
                    elif is_downstream:
                        downstream += channel.real_traffic

                return(downstream,upstream)
				
	def get_d30_down(self):
		d30=0
		for channel in self.channels:
			if "D3.0" in channel.type_docsis and channel.name[0]!='U':
				d30+=1
		return d30
		
	def get_d31_down(self):
		d31=0
		for channel in self.channels:
			if "D3.1" in channel.type_docsis and channel.name[0]!='U':
				d31+=1
		return d31
	
	def get_d30_up(self):
		d30=0
		for channel in self.channels:
			if "D3.0" in channel.type_docsis and channel.name[0]=='U':
				d30+=1
		return d30
		
	def get_d31_up(self):
		d31=0
		for channel in self.channels:
			if "D3.1" in channel.type_docsis and channel.name[0]=='U':
				d31+=1
		return d31
                    

	def add_channel(self,name,total,d20,d30,d31,real_traffic,max_traffic):
		type_docsis = "D3.0"
		if d20 >0 :
			type_docsis = "D2.0&D3.0"
		else:
			is_upstream = name[0]=='U'
                	channel_number = int(name[1:])
                	if is_upstream :
                        	if channel_number > 10:
                                	type_docsis = "D3.1"
                	else:
                        	if channel_number > 32:
                                	type_docsis = "D3.1"

		if max_traffic == 0:
			type_docsis = "Docsis disabled"

		utilization = d20 + d30 + d31
		self.channels.append(Docsis_Channel(name,type_docsis,utilization,real_traffic,max_traffic))

class HuaweiOLTSSH(CiscoSSHConnection):

    def session_preparation(self):
        """Prepare the session after the connection has been established."""
        self._test_channel_read()
        self.set_base_prompt()
        self.disable_paging(command="scroll 512 ")
        # Clear the read buffer
        time.sleep(.3 * self.global_delay_factor)
        self.clear_buffer()
        self.fast_cli=True

    def config_mode(self, config_command='config'):
        """Enter configuration mode."""
        return super(HuaweiOLTSSH, self).config_mode(config_command=config_command)

    def exit_config_mode(self, exit_config='quit', pattern=r'#'):
        """Exit configuration mode."""
        return super(HuaweiOLTSSH, self).exit_config_mode(exit_config=exit_config,
                                                       pattern=pattern)

    def check_config_mode(self, check_string=')#'):
        """Checks whether in configuration mode. Returns a boolean."""
        return super(HuaweiOLTSSH, self).check_config_mode(check_string=check_string)

    def save_config(self, cmd='save', confirm=False, confirm_response=''):
        """ Save Config for HuaweiOLTSSH"""
        return super(HuaweiOLTSSH, self).save_config(cmd=cmd, confirm=confirm)

def print_header():
        if args.per_channel_bw:
			print("time,olt_name,ip_address,gpon_port,interface_cable,alias_name,channel,type_docsis,channel_utilization,real_traffic,max_traffic")
        else:
			print("time,olt_name,ip_address,gpon_port,interface_cable,alias_name,cm_total,cm_online,cm_offline,downstream_traffic,upstream_traffic,D30_Down,D30_Up,D31_Down,D31_Up")

			
def polling_olt(olt_name,ip_address,ssh_user,ssh_pwd):

	current_olt = OLT(olt_name,ip_address);		
	net_connect = HuaweiOLTSSH(host=ip_address,username=ssh_user, password=ssh_pwd,device_type='cisco_ios')
	net_connect.enable()
	output = net_connect.send_command("display frame extension\n\n",normalize=False)

	template1 = open(os.environ['Scripts_Polling'] + "pollOLTChannels/olt_display_frame_extension.template")
	template2 = open(os.environ['Scripts_Polling'] + "pollOLTChannels/olt_cable_channel_utilization.template")
	template3 = open(os.environ['Scripts_Polling'] + "pollOLTChannels/olt_display_cable_modem_summary_statistics.template")
	re_table = textfsm.TextFSM(template1)
	output=output.replace("\nCommunicationFail","     CommunicationFail")
	fsm_results = re_table.ParseText(output)

	#print(fsm_results)
	re_table = None
	re_table = textfsm.TextFSM(template3)
	output = net_connect.send_command("display cable modem summary statistics\n\n",normalize=False)
	fsm_results3 = re_table.ParseText(output)
	#print(fsm_results)

	if len(fsm_results3)>0:
		for row in fsm_results3:
					dccap_interface_name = "CABLE " + str(row[0]).replace(" ","")
					dccap_cm_total = int(row[1])
					dccap_cm_online = int(row[2])
					dccap_cm_offline = int(row[3])
					dccap_cm[dccap_interface_name] = DCCAP_modems_summary(dccap_cm_total,dccap_cm_online,dccap_cm_offline) 

	#re_table = textfsm.TextFSM(template2)
	first_time = True
	if len(fsm_results) > 0:
		dt_string = datetime.now().strftime("%d/%m/%Y %H:%M:%S")
		for row in fsm_results:
			re_table = None
			re_table = textfsm.TextFSM(template2)
			dccap_olt_gpon_port = str(row[0])
			dccap_interface_name = "CABLE " + str(row[2]) + "/1/0"
			dccap_sn = str(row[3])
			dccap_status = str(row[5])
			dccap_alias = str(row[7])
	#		print(dccap_alias)
			command = "display cable channel utilization " + str(row[2]) + "/1/0" + "\n\n"
			try:
				output = net_connect.send_command(command,normalize=False)
			except:
				print("Error with command: " + command)
				continue
			fsm_results2 = re_table.ParseText(output)
			current_dccap = DCCAP(olt_name,dccap_olt_gpon_port,dccap_interface_name,dccap_alias,dccap_sn,dccap_status)
			if dccap_interface_name in dccap_cm:
				current_dccap.cable_modem_summary = dccap_cm[dccap_interface_name]
			else:
				current_dccap.cable_modem_summary = DCCAP_modems_summary(0,0,0)

			for channel_row in fsm_results2:
				#print("command" + channel_row[0])
				try:
					current_dccap.add_channel(channel_row[0],channel_row[1],int(channel_row[2]),int(channel_row[3]),int(channel_row[4]),int(channel_row[5]),int(channel_row[6]))
				except:
					current_dccap.add_channel(channel_row[0],channel_row[1],0,0,0,int(channel_row[5]),int(channel_row[6]))
			dccap.append(current_dccap)
			
			if first_time:
				first_time=False
				if args.out_influxdb==False:
					print_header()
			if args.per_channel_bw:
				for current_channel in current_dccap.channels:
					str_list = []
					if args.out_influxdb==False:
						str_list.append(dt_string)
					str_list.append(olt_name)
					str_list.append(ip_address)
					str_list.append(current_dccap.gpon_port)
					str_list.append(current_dccap.interface_cable)
					str_list.append(current_dccap.alias_name)
					str_list.append((",").join(current_channel.print_summary()))
					if args.out_influxdb==False:
						print((",").join(str_list))
			else:
				(dccap_down,dccap_up)=(current_dccap.get_total_bandwidth()) 
				str_list = []
				str_list.append(olt_name)
				str_list.append(ip_address)
				str_list.append(current_dccap.gpon_port)
				str_list.append(current_dccap.interface_cable)
				str_list.append(current_dccap.alias_name)
				str_list.append(str(current_dccap.cable_modem_summary.total))
				str_list.append(str(current_dccap.cable_modem_summary.online))
				str_list.append(str(current_dccap.cable_modem_summary.offline))
				str_list.append(str(dccap_down))
				str_list.append(str(dccap_up))
				str_list.append(str(current_dccap.get_d30_down()))
				str_list.append(str(current_dccap.get_d30_up()))
				str_list.append(str(current_dccap.get_d31_down()))
				str_list.append(str(current_dccap.get_d31_up()))
				if args.out_influxdb==False:
					print((",").join(str_list))
				else:
					current_dccap.update_influx_db()
					current_olt.total_dccaps+=1
					current_olt.total_cm+=current_dccap.cable_modem_summary.total
					current_olt.total_cm_online+=current_dccap.cable_modem_summary.online
					current_olt.total_cm_offline+=current_dccap.cable_modem_summary.offline
					current_olt.uplink+=dccap_up
					current_olt.downlink+=dccap_down


	if args.out_influxdb:
			DCCAPSeriesHelper.commit()
			current_olt.update_influx_db()
			OLTSeriesHelper.commit()

	net_connect.disconnect()

if args.olt_file_name != "":
	with open(args.olt_file_name) as csv_file:
		csv_reader = csv.reader(csv_file, delimiter=',')
		for row in csv_reader:
			olt_list[row[0]]=row[1]

if len(olt_list)>0:
	for olt_name in olt_list:
		try:
			print(olt_name)
			polling_olt(olt_name,olt_list[olt_name],args.ssh_user,args.ssh_pwd)
		except Exception as e:
			print(e)
			continue
else:
	if(args.olt_name=="" or args.ip_address==""):
		print("Error: OLT name or ip address not defined")
	else:
		polling_olt(args.olt_name,args.ip_address,args.ssh_user,args.ssh_pwd)
