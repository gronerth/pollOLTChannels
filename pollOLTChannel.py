import time
import re
from netmiko.cisco_base_connection import CiscoSSHConnection
from netmiko import log
import textfsm
import argparse


dccap = []


parser = argparse.ArgumentParser(description='Poll parameters from OLT')
parser.add_argument('--ip',dest='ip_address',required=True,help='Hostname or IP Address')
parser.add_argument('--olt',dest='olt_name',required=True,help='Name of the OLT')
parser.add_argument('--ssh_user',dest='ssh_user',default='rfalla',help='SSH user to connect to OLT')
parser.add_argument('--ssh_pwd',dest='ssh_pwd',default='rfalla214',help='SSH users password to connect to OLT')
parser.add_argument('--community',dest='community',default='u2000_ro',help='SNMP read community')
parser.add_argument('--per_channel_bw',dest='per_channel_bw',default=False,help='True if you want traffic per channel')

args = parser.parse_args()

class Docsis_Channel():
	def __init__(self,name,type_docsis,utilization,real_traffic,max_traffic):
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

class DCCAP():
	def __init__(self,olt_gpon_port,interface_cable,alias_name,serial,status):
		self.interface_cable = interface_cable;
		self.alias_name = alias_name
		self.gpon_port = olt_gpon_port
		self.serial = serial
		self.status = status
		self.channels = []
	
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
        self.disable_paging(command="scroll 512")
        # Clear the read buffer
        time.sleep(.3 * self.global_delay_factor)
        self.clear_buffer()

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
	    print("olt_name,ip_address,gpon_port,interface_cable,alias_name,channel,type_docsis,channel_utilization,real_traffic,max_traffic")
        else:
	    print("olt_name,ip_address,gpon_port,interface_cable,alias_name,downstream_traffic,upstream_traffic")

		
net_connect = HuaweiOLTSSH(host=args.ip_address,username=args.ssh_user, password=args.ssh_pwd,device_type='cisco_ios')
net_connect.enable()
output = net_connect.send_command("display frame extension\n\n",normalize=False)

template1 = open("olt_display_frame_extension.template")
template2 = open("olt_cable_channel_utilization.template")
re_table = textfsm.TextFSM(template1)
fsm_results = re_table.ParseText(output)

#re_table = textfsm.TextFSM(template2)
first_time = True
if len(fsm_results) > 0:
	for row in fsm_results:
                re_table = None
                re_table = textfsm.TextFSM(template2)
                dccap_olt_gpon_port = str(row[0])
		dccap_interface_name = "CABLE " + str(row[2]) + "/1/0"
		#print(dccap_interface_name)
		dccap_sn = str(row[3])
		dccap_status = str(row[5])
		dccap_alias = str(row[7])
		command = "display cable channel utilization " + str(row[2]) + "/1/0" + "\n\n"
		output = net_connect.send_command(command,normalize=False)
		fsm_results2 = re_table.ParseText(output)
                current_dccap = DCCAP(dccap_olt_gpon_port,dccap_interface_name,dccap_alias,dccap_sn,dccap_status)
		for channel_row in fsm_results2:
			current_dccap.add_channel(channel_row[0],channel_row[1],int(channel_row[2]),int(channel_row[3]),int(channel_row[4]),int(channel_row[5]),int(channel_row[6]))
		dccap.append(current_dccap)
		
		if first_time:
			first_time=False
			print_header()
                if args.per_channel_bw:
		        for current_channel in current_dccap.channels:
			    str_list = []
			    str_list.append(args.olt_name)
			    str_list.append(args.ip_address)
			    str_list.append(current_dccap.gpon_port)
			    str_list.append(current_dccap.interface_cable)
			    str_list.append(current_dccap.alias_name)
			    str_list.append((",").join(current_channel.print_summary()))
			    print((",").join(str_list))
                else:
			    (dccap_down,dccap_up)=(current_dccap.get_total_bandwidth()) 
                            str_list = []
			    str_list.append(args.olt_name)
			    str_list.append(args.ip_address)
			    str_list.append(current_dccap.gpon_port)
			    str_list.append(current_dccap.interface_cable)
			    str_list.append(current_dccap.alias_name)
			    str_list.append(str(dccap_down))
			    str_list.append(str(dccap_up))
			    print((",").join(str_list))


net_connect.disconnect()


