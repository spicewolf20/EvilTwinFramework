# -*- coding: utf-8 -*-
'''
This is a wrapper class responsible for
everything that concerns air communications
such as setting up the access point as well
as sniffing the packets in the air
'''

from pyric.pyw import interfaces, winterfaces
from airhost import AirHost
from airscanner import AirScanner
from airdeauthor import AirDeauthenticator
from aircracker import AirCracker
from Plugins.plugin import Plugin, AirHostPlugin, AirScannerPlugin, AirDeauthorPlugin
from AuxiliaryModules.infoprinter import InfoPrinter, ObjectFilter
from AuxiliaryModules.wpacracker import WPACracker
from Plugins.dnsspoofer import DNSSpoofer
from Plugins.selfishwifi import SelfishWiFi
from Plugins.packetlogger import PacketLogger
from Plugins.credentialsniffer import CredentialSniffer
from Plugins.karma import Karma
from ConfigurationManager.configmanager import ConfigurationManager
from utils.networkmanager import NetworkManager, NetworkCard
from textwrap import dedent
from time import sleep

class AirCommunicator(object):

	def __init__(self):
		self.configs = ConfigurationManager().config["etf"]["aircommunicator"]
		self.config_files = ConfigurationManager().config["etf"]["config_location"]

		self.air_host = AirHost(self.config_files["hostapd_conf"], self.config_files["dnsmasq_conf"])
		self.air_scanner = AirScanner()
		self.air_deauthenticator = AirDeauthenticator()
		self.air_cracker = AirCracker()
		self.network_manager = NetworkManager(self.config_files["networkmanager_conf"])

		self.info_printer = InfoPrinter()

	def start_deauthentication_attack(self, plugins = []):
		if not self.air_deauthenticator.deauth_running:
			jamming_interface = self.configs["airdeauthor"]["jamming_interface"]
			if jamming_interface not in winterfaces():
				print "[-] jamming_interface '{}' does not exist".format(jamming_interface)
				return

			burst_count = 5
			targeted_only = False
			for arg in self.configs["airdeauthor"].keys():
				try:
					val = self.configs["airdeauthor"][arg]
					if arg == "burst_count":    burst_count = int(val)
					else:                       targeted_only = True if str(val).lower() == "true" else False
				except ValueError:
					print "[-] Burst count must be in integer form, not changing value."
				except KeyError:
					pass
		
			self.add_plugins(plugins, self.air_deauthenticator, AirDeauthorPlugin)
			self.air_deauthenticator.set_burst_count(int(burst_count))
			self.air_deauthenticator.set_targeted(targeted_only)
			self.air_deauthenticator.start_deauthentication_attack(jamming_interface)
		else:
			print "[-] Deauthentication attack still running"

	def start_access_point(self, plugins = []):
		'''
		This method is responsible for starting the access point with hostapd 
		while also avoiding conflicts with NetworkManager.
		It replaces the original NetworkManager.conf file
		and adding some lines that tell it to ignore managing the interface 
		that we are going to use as AP then it restarts the service
		'''

		# Start by getting all the info from the configuration file
		try:
			ap_interface = self.configs["airhost"]["ap_interface"]
			internet_interface = self.configs["airhost"]["internet_interface"]
			gateway = self.configs["airhost"]["dnsmasqhandler"]["gateway"]
			dhcp_range = self.configs["airhost"]["dnsmasqhandler"]["dhcp_range"]
			ssid = self.configs["airhost"]["aplauncher"]["ssid"]
			bssid = self.configs["airhost"]["aplauncher"]["bssid"]
			channel = self.configs["airhost"]["aplauncher"]["channel"]
			hw_mode = self.configs["airhost"]["aplauncher"]["hw_mode"]
			dns_servers = self.configs["airhost"]["dnsmasqhandler"]["dns_server"]
		except KeyError as e:
			print "[-] Unable to start Access Point, too few configurations"
			return False

		if  ap_interface not in winterfaces():
			print "[-] ap_interface '{}' does not exist".format(ap_interface)
			return False

		if internet_interface not in interfaces():
			print "[-] internet_interface '{}' does not exist".format(internet_interface)
			return False

		# Add plugins
		self.add_plugins(plugins, self.air_host, AirHostPlugin)

		# NetworkManager setup
		is_catch_all_honeypot 	= self.configs["airhost"]["aplauncher"]["catch_all_honeypot"].lower() == "true"
		is_multiple_ssid		= type(ssid) is list
		nVirtInterfaces 		= 3 			if is_catch_all_honeypot else \
								  len(ssid)		if is_multiple_ssid else \
								  0
		if self.network_manager.set_mac_and_unmanage(	ap_interface, bssid, 
														retry = True, 
														virtInterfaces = nVirtInterfaces):

			# Initial configuration
			self.network_manager.configure_interface(ap_interface, gateway)
			self.network_manager.iptables_redirect(ap_interface, internet_interface)
			
			# dnsmasq and hostapd setup
			try:
				captive_portal_mode = self.configs["airhost"]["dnsmasqhandler"]["captive_portal_mode"].lower() == "true"
			except KeyError:
				captive_portal_mode = False

			self.air_host.dnsmasqhandler.set_captive_portal_mode(captive_portal_mode)
			self.air_host.dnsmasqhandler.write_dnsmasq_configurations(	ap_interface, gateway, dhcp_range, dns_servers,
																		nVirtInterfaces)
			try:
				self.air_host.aplauncher.write_hostapd_configurations(
					interface=ap_interface, ssid=ssid, bssid=bssid, channel=channel, hw_mode=hw_mode,
					encryption=self.configs["airhost"]["aplauncher"]["encryption"], 
					auth=self.configs["airhost"]["aplauncher"]["auth"],
					cipher=self.configs["airhost"]["aplauncher"]["cipher"],
					password=self.configs["airhost"]["aplauncher"]["password"],
					catch_all_honeypot=is_catch_all_honeypot)
			except KeyError:
				self.air_host.aplauncher.write_hostapd_configurations(
					interface=ap_interface, ssid=ssid, bssid=bssid, channel=channel, hw_mode=hw_mode)
			except Exception as e:
				print e
				return

			# Start services
			print_creds = self.configs["airhost"]["aplauncher"]["print_creds"].lower() == "true"
			self.air_host.start_access_point(   ap_interface, 
												print_creds)

			# Configure Virtual Interfaces once hostapd has set them up
			sleep(.5) # Wait for for hostapd to setup interfaces
			extra_interfaces = False
			for i in range(nVirtInterfaces-1):
				interface_name = "{}_{}".format(ap_interface, i)
				if interface_name in winterfaces():
					gateway = ".".join(gateway.split(".")[0:2] + [str(int(gateway.split(".")[2]) + 1)] + [gateway.split(".")[3]])
					self.network_manager.configure_interface(interface_name, gateway)
					self.network_manager.iptables_redirect(interface_name, internet_interface)
					extra_interfaces = True

			# Needed for dnsmasq to work correctly with virtual interfaces once they are configured
			if extra_interfaces:
				self.air_host.dnsmasqhandler.start_dnsmasq() 

			return True

		print dedent("""
					[-] Errors occurred while trying to start access point, 
					try restarting network services and unplug your network adapter""")
		return False
		
	def start_sniffer(self, plugins = []):
		# Sniffing options
		if not self.air_scanner.sniffer_running:
			self.add_plugins(plugins, self.air_scanner, AirScannerPlugin)

			sniff_probes = self.configs["airscanner"]["probes"].lower() == "true"
			sniff_beacons = self.configs["airscanner"]["beacons"].lower() == "true"
			hop_channels = self.configs["airscanner"]["hop_channels"].lower() == "true"
			try:
				fixed_sniffing_channel = int(self.configs["airscanner"]["fixed_sniffing_channel"])
				if fixed_sniffing_channel > 13:
					raise
			except:
				print "Channel must be an integer and below 14\n"
				return

			sniffing_interface = self.configs["airscanner"]["sniffing_interface"]
			if  sniffing_interface not in winterfaces():
				print "[-] sniffing_interface '{}' does not exist".format(sniffing_interface)
				return

			mac = self.configs["airhost"]["aplauncher"]["bssid"]

			if not self.network_manager.set_mac_and_unmanage(sniffing_interface, mac, retry = True):
				print "[-] Unable to set mac and unmanage, resetting interface and retrying."
				print "[-] Sniffer will probably crash."

			self.air_scanner.set_probe_sniffing(sniff_probes)
			self.air_scanner.set_beacon_sniffing(sniff_beacons)
			self.air_scanner.start_sniffer(sniffing_interface, hop_channels, fixed_sniffing_channel)
				
		else:
			print "[-] Sniffer already running"

	def add_plugins(self, plugins, airmodule, baseclass):
		for airhost_plugin in baseclass.__subclasses__():
			airhost_plugin_instance = airhost_plugin()
			if airhost_plugin_instance.name in plugins:
				airmodule.add_plugin(airhost_plugin_instance)

	def stop_air_communications(self, stop_sniffer, stop_ap, stop_deauth):
		if stop_sniffer and self.air_scanner.sniffer_running:
			self.air_scanner.stop_sniffer()
			self.network_manager.cleanup_filehandler()

		if stop_ap and self.air_host.is_running():
			self.air_host.stop_access_point()
			self.air_host.cleanup()
			self.network_manager.cleanup()

		if stop_deauth and self.air_deauthenticator.deauth_running:
			self.air_deauthenticator.stop_deauthentication_attack()

	def service(self, service, option, plugins = []):
		if service == "airdeauthor":
			if option == "start":
				self.start_deauthentication_attack(plugins)
			else:
				self.stop_air_communications(False, False, True)
		elif service == "airhost":
			if option == "start":
				self.start_access_point(plugins)
			else:
				self.stop_air_communications(False, True, False)
		elif service == "airscanner":
			if option == "start":
				self.start_sniffer(plugins)
			else:
				self.stop_air_communications(True, False, False)


	# APLauncher action methods
	def airhost_copy_ap(self, id):
		password_info = dedent( """ 
								Note:   The AP you want to copy uses encryption, 
										you have to specify the password in the airhost/aplauncher configurations.
								""")
		bssid_info = dedent("""
							Note:   Issues will arise when starting the 
									rogue access point with a bssid that exists nearby.
							""")
		access_point = self.air_scanner.get_access_point(id)
		if access_point:
			self.configs["airhost"]["aplauncher"]["ssid"] = access_point.ssid
			self.configs["airhost"]["aplauncher"]["bssid"] = access_point.bssid
			self.configs["airhost"]["aplauncher"]["channel"] = access_point.channel

			self.configs["airhost"]["aplauncher"]["encryption"] = access_point.crypto
			self.configs["airhost"]["aplauncher"]["auth"] = access_point.auth
			self.configs["airhost"]["aplauncher"]["cipher"] = access_point.cipher

			if self.configs["airhost"]["aplauncher"]["encryption"].lower() != "opn":
				print password_info

			print bssid_info
			ConfigurationManager().config.write() # Singleton perks ;)
		else:
			print "[-] No access point with ID = {}".format(str(id))
		
	def airhost_copy_probe(self, id):
		probe = self.air_scanner.get_probe_request(id)
		if probe:
			if not probe.ap_ssid or probe.ap_ssid == "":
				print "[-] Probe request needs to specify SSID or it cannot be copied."
				return

			self.configs["airhost"]["aplauncher"]["ssid"] = probe.ap_ssid

			# TODO if it has bssid it's because the AP is listed in the AP list
			if probe.ap_bssids:
				self.configs["airhost"]["aplauncher"]["bssid"] = probe.ap_bssids[0]

			self.configs["airhost"]["aplauncher"]["encryption"] = "None"

			ConfigurationManager().config.write() # Singleton perks ;)
		else:
			print "[-] No probe with ID = {}".format(str(id))

	# Deauthor action methods
	def deauthor_add(self, add_type, filter_string):
		if add_type == "aps":
			add_list = ObjectFilter().filter(self.air_scanner.get_access_points(), filter_string)
			for ap in add_list:
				self.air_deauthenticator.add_ap(ap.bssid, ap.ssid, ap.channel)
		elif add_type == "clients":
			self.air_scanner.update_bssids_in_probes()
			add_list = ObjectFilter().filter(self.air_scanner.get_probe_requests(), filter_string)
			for client in add_list:
				client_mac = client.client_mac
				try:
					if len(client.ap_bssids) > 0:
						for bssid in client.ap_bssids:
							if bssid and bssid != "":
								self.air_deauthenticator.add_client(client_mac, bssid, client.ap_ssid)
				except:
					print "[-] Cannot add client '{}' because no AP bssid is associated".format(client_mac)
	

	def deauthor_del(self, del_type, filter_string):
		if del_type == "aps":
			del_list = set(ObjectFilter().filter(self.air_deauthenticator.aps_to_deauth, filter_string))
			self.air_deauthenticator.del_aps(del_list)
		elif del_type == "clients":
			del_list = ObjectFilter().filter(self.air_deauthenticator.clients_to_deauth, filter_string)
			self.air_deauthenticator.del_clients(del_list)

	def crack_handshake(self, id, is_half):
		wpa_cracker = self.wpa_cracker_from_conf(is_half)
		self.air_cracker.launch_handshake_cracker(id, is_half, wpa_cracker)

	def wpa_cracker_from_conf(self, is_half):
		aircracker_conf = self.configs["aircracker"]
		wpa_cracker = aircracker_conf["half_wpa_cracker"] if is_half else aircracker_conf["wpa_cracker"]
		wpa_cracker_conf = aircracker_conf["half_wpa_crackers" if is_half else "wpa_crackers"][wpa_cracker]
		return WPACracker(	wpa_cracker_conf["name"], wpa_cracker_conf["location"], 
							wpa_cracker_conf["ssid_flag"], wpa_cracker_conf["pcap_flag"], wpa_cracker_conf["wordlist_flag"],
							aircracker_conf["ssid"], aircracker_conf["pcap_file"], aircracker_conf["wordlist_file"],
							aircracker_conf["wordlist_generator_string"])

	# Informational print methods
	def print_sniffed_aps(self, filter_string = None):
		ap_list = self.air_scanner.get_access_points()
		ap_arg_list = [ "id","bssid","ssid","channel","rssi",
						"crypto","cipher","auth"]
		headers = ["ID:", "BSSID:", "SSID:", "CHANNEL:", "SIGNAL:", "CRYPTO:", "CIPHER:", "AUTH:"]
		self.info_printer.add_info("sniffed_ap", ap_list, ap_arg_list, headers)
		self.info_printer.print_info("sniffed_ap", filter_string)

	def print_sniffed_clients(self, filter_string = None):
		client_list = self.air_scanner.get_wifi_clients()
		client_arg_list = [ "id","client_mac","client_org","probed_ssids","associated_ssid","rssi"]
		headers = ["ID:", "MAC:", "CLIENT ORG:", "PROBED SSIDS:", "ASSOCIATED SSID:", "SIGNAL:"]
		self.info_printer.add_info("sniffed_wifi_clients", client_list, client_arg_list, headers)
		self.info_printer.print_info("sniffed_wifi_clients", filter_string)

	def print_sniffed_probes(self, filter_string = None):
		self.air_scanner.update_bssids_in_probes()
		probe_list = self.air_scanner.get_probe_requests()
		probe_arg_list = ["id","client_mac","client_org","ap_ssid","ap_bssids","rssi","type"]
		headers = ["ID:", "CLIENT MAC:", "CLIENT ORG:", "AP SSID:", "AP BSSID:", "SIGNAL:", "TYPE:"]
		self.info_printer.add_info("sniffed_probe", probe_list, probe_arg_list, headers)
		self.info_printer.print_info("sniffed_probe", filter_string)

	def print_aps_to_deauth(self, filter_string = None):
		bssid_list = list(self.air_deauthenticator.aps_to_deauth)
		bssid_arg_list = ["id","bssid","ssid", "channel"]
		headers = ["ID:", "AP BSSID:", "AP SSID", "AP CHANNEL"]
		self.info_printer.add_info("deauth_bssid", bssid_list, bssid_arg_list, headers)
		self.info_printer.print_info("deauth_bssid", filter_string)

	def print_clients_to_deauth(self, filter_string = None):
		client_list = list(self.air_deauthenticator.clients_to_deauth)
		client_arg_list = ["id","client_mac","ap_bssid","ap_ssid"]
		headers = ["ID:", "CLIENT MAC:", "AP BSSID:", "AP SSID:"]
		self.info_printer.add_info("deauth_client", client_list, client_arg_list, headers)
		self.info_printer.print_info("deauth_client", filter_string)

	def print_connected_clients(self, filter_string = None):
		client_list = self.air_host.aplauncher.get_connected_clients()
		client_arg_list = ["id","name","mac_address","ip_address","vendor","connected_ssid","rx_packets","tx_packets","signal"]
		headers = ["ID:", "CLIENT NAME:", "CLIENT MAC:", "CLIENT IP:", "VENDOR:", "CONNECTED NET:", "RX PACKETS:", "TX PACKETS:", "SIGNAL:"]
		self.info_printer.add_info("connected_client", client_list, client_arg_list, headers)
		self.info_printer.print_info("connected_client", filter_string)

	def print_captured_handshakes(self, filter_string = None, is_half = False):
		self.air_cracker.load_half_wpa_handshakes() if is_half else self.air_cracker.load_wpa_handshakes()
		info_key = "half_wpa_handshakes" if is_half else "wpa_handshakes"
		handshake_list = self.air_cracker.half_wpa_handshakes if is_half else self.air_cracker.wpa_handshakes
		handshake_args = ["id", "ssid", "client_mac", "client_org"]
		handshake_headers = ["ID:", "SSID:", "CLIENT MAC:", "CLIENT ORG:"]
		self.info_printer.add_info(info_key, handshake_list, handshake_args, handshake_headers)
		self.info_printer.print_info(info_key, filter_string)
