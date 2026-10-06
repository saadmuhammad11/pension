<?php
/**
 *
 * This file is part of HESK - PHP Help Desk Software.
 *
 * (c) Copyright Klemen Stirn. All rights reserved.
 * https://www.hesk.com
 *
 * For the full copyright and license agreement information visit
 * https://www.hesk.com/eula.php
 *
 */

define('IN_SCRIPT',1);
define('HESK_PATH','../');
require_once(HESK_PATH . 'api/Rabbitmq.php');

/* Get all the required files and functions */
require(HESK_PATH . 'hesk_settings.inc.php');
require(HESK_PATH . 'inc/common.inc.php');
require(HESK_PATH . 'inc/admin_functions.inc.php');
//require(HESK_PATH . 'api/pusher.php');
hesk_load_database_functions();

hesk_session_start();
hesk_dbConnect();
hesk_isLoggedIn();

/* Check permissions for this feature */
hesk_checkPermission('can_view_tickets');

/* A security check */
hesk_token_check();

/* Ticket ID */
$trackingID = hesk_cleanID() or die($hesklang['int_error'].': '.$hesklang['no_trackID']);

// Load statuses
require_once(HESK_PATH . 'inc/statuses.inc.php');

/* New status */
$status = intval( hesk_REQUEST('s') );
echo $status;exit;
if ( ! isset($hesk_settings['statuses'][$status]))
{
	hesk_process_messages($hesklang['instat'],'admin_ticket.php?track='.$trackingID.'&Refresh='.mt_rand(10000,99999),'NOTICE');
}

// We need can_reply_tickets permission unless we are closing a ticket
if ($status != 3)
{
    hesk_checkPermission('can_reply_tickets');
 }

$locked = 0;

//---------check noting start-----------
if($trackingID){
	$result = hesk_dbQuery("SELECT * FROM `".hesk_dbEscape($hesk_settings['db_pfix'])."tickets` WHERE `trackid`='".hesk_dbEscape($trackingID)."' LIMIT 1");
	if (hesk_dbNumRows($result) != 1)
	{
		hesk_error($hesklang['ticket_not_found']);
	}
	$ticket = hesk_dbFetchAssoc($result);
	$ticket['dt'] = hesk_date($ticket['dt'], true);
	$ticket['lastchange'] = hesk_date($ticket['lastchange'], true);
    $ticket['due_date'] = hesk_format_due_date($ticket['due_date']);
	$ticket = hesk_ticketToPlain($ticket, 1, 0);


	$getMessage = hesk_dbQuery("SELECT * FROM `".hesk_dbEscape($hesk_settings['db_pfix'])."notes` WHERE `ticket`='".hesk_dbEscape($ticket['id'])."' AND dt LIKE '".date('Y-m-d')."%' ORDER BY id DESC LIMIT 1");
		$msg = "";
		if (hesk_dbNumRows($getMessage) != 1)
		{
			hesk_process_messages('Please add noting before update ticket status.','admin_ticket.php?track='.$trackingID.'&Refresh='.rand(10000,99999),'ERROR');
			hesk_error("Notes not found.");
		}
		
	
}	
//---------check noting end-------------

$pushData = [];
if ($status == 3) // Closed
{
    if ( ! hesk_checkPermission('can_resolve', 0))
    {
        hesk_process_messages($hesklang['noauth_resolve'],'admin_ticket.php?track='.$trackingID.'&Refresh='.mt_rand(10000,99999),'NOTICE');
    }

	$action = $hesklang['ticket_been'] . ' ' . $hesklang['closed'];
    $revision = sprintf($hesklang['thist3'],hesk_date(),addslashes($_SESSION['name']).' ('.$_SESSION['user'].')');

    if ($hesk_settings['custopen'] != 1)
    {
    	$locked = 1;
    }

	// Notify customer of closed ticket?
	if ($hesk_settings['notify_closed'])
	{
		// Get ticket info
		$result = hesk_dbQuery("SELECT * FROM `".hesk_dbEscape($hesk_settings['db_pfix'])."tickets` WHERE `trackid`='".hesk_dbEscape($trackingID)."' LIMIT 1");
		
		if (hesk_dbNumRows($result) != 1)
		{
			hesk_error($hesklang['ticket_not_found']);
		}
		$ticket = hesk_dbFetchAssoc($result);
		$ticket['dt'] = hesk_date($ticket['dt'], true);
		$ticket['lastchange'] = hesk_date($ticket['lastchange'], true);
        $ticket['due_date'] = hesk_format_due_date($ticket['due_date']);
		$ticket = hesk_ticketToPlain($ticket, 1, 0);
		// Notify customer
		require(HESK_PATH . 'inc/email_functions.inc.php');
		hesk_notifyCustomer('ticket_closed');
	}
	
	
	// Log who marked the ticket resolved
	$closedby_sql = ' , `closedat`=NOW(), `closedby`='.intval($_SESSION['id']).' ';
	if($ticket['officer_id'] > 0){
		//	echo __LINE__; exit;
		//print_r($ticket);exit;
		$getMessage = hesk_dbQuery("SELECT * FROM `".hesk_dbEscape($hesk_settings['db_pfix'])."notes` WHERE `ticket`='".hesk_dbEscape($ticket['id'])."' ORDER BY id DESC LIMIT 1");
		$msg = "";
		if (hesk_dbNumRows($getMessage) != 1)
		{
			hesk_error("Notes not found.");
		}
		$msg = hesk_dbFetchAssoc($getMessage);
		$pushData['officer_id'] = $ticket['officer_id'];
		$pushData['retirement_id'] = $ticket['retirement_id'];
		$pushData['cnic'] = $ticket['custom3'];
		$pushData['message'] = $msg['message'];
		$pushData['status_date'] = date('Y-m-d h:i:s',strtotime($msg['dt']));
		$pushData['request_status'] = "Resolved";
		$pushData['department'] = $ticket['custom23'];
		//print_r($pushData);exit;
		//$pushData1['test'] = 'This is testing message.';
		//pushData(json_encode($pushData));
		$datee = date('Y-m-d H:i:s');
		hesk_dbQuery("UPDATE `hesk_ag_pentickets` SET `dt` = '".$datee."' WHERE `id`='".$ticket['id']."'");
		
		$pusher       = new Rabbitmq_client();
		if($ticket['custom23']=='SNGAD'){
			$listenQueue    = 'ag_pension_sngad_pull';
		}else if($ticket['custom23']=='BOR'){
			$listenQueue    = 'ag_pension_bor_pull';
		}else if($ticket['custom23']=='CNW'){
			$listenQueue    = 'ag_pension_cnw_pull';
		}else if($ticket['custom23']=='COOPERATIVES'){
			$listenQueue    = 'ag_pension_cooperative_pull';
		}else if($ticket['custom23']=='MPDD'){
			$listenQueue    = 'ag_pension_mpdd_pull';
		}else if($ticket['custom23']=='PND'){
			$listenQueue    = 'ag_pension_pnd_pull';
		}
		else if($ticket['custom23']=='IRRIGATION'){
			$listenQueue    = 'ag_pension_irrigation_pull';
		}else if($ticket['custom23']=='SWD'){
			$listenQueue    = 'ag_pension_swd_pull';
		}else if($ticket['custom23']=='GS'){
			$listenQueue    = 'ag_pension_gs_pull';
		}else if($ticket['custom23']=='LNPF'){
			$listenQueue    = 'ag_pension_lnpf_pull';
		}else if($ticket['custom23']=='LIVESTOCK'){
			$listenQueue    = 'ag_pension_livestock_pull';
		}else if($ticket['custom23']=='TRANSPORT'){
			$listenQueue    = 'ag_pension_transport_pull';
		}else if($ticket['custom23']=='INC'){
			$listenQueue    = 'ag_pension_inc_pull';
		}else if($ticket['custom23']=='EXCISE'){
			$listenQueue    = 'ag_pension_excise_pull';
		}else if($ticket['custom23']=='HRMA'){
			$listenQueue    = 'ag_pension_hrma_pull';
		}else if($ticket['custom23']=='MNM'){
			$listenQueue    = 'ag_pension_mnm_pull';
		}else if($ticket['custom23']=='ACE'){
			$listenQueue    = 'ag_pension_ace_pull';
		}else if($ticket['custom23']=='AUQAF'){
			$listenQueue    = 'ag_pension_auqaf_pull';
		}else if($ticket['custom23']=='ZAKAT'){
			$listenQueue    = 'ag_pension_zakat_pull';
		}else if($ticket['custom23']=='LITERACY'){
			$listenQueue    = 'ag_pension_literacy_pull';
		}else if($ticket['custom23']=='HED'){
			$listenQueue    = 'ag_pension_hed_pull';
		}

		else if($ticket['custom23']=='ICI'){
			$listenQueue = 'ag_pension_ici_pull';
		}else if($ticket['custom23']=='LABOUR'){
			$listenQueue = 'ag_pension_labour_pull';
		}else if($ticket['custom23']=='LGCD'){
			$listenQueue = 'ag_pension_lgcd_pull';
		}else if($ticket['custom23']=='SPECIALEDU'){
			$listenQueue = 'ag_pension_specialedu_pull';
		}else if($ticket['custom23']=='TOURISM'){
			$listenQueue = 'ag_pension_tourism_pull';
		}else if($ticket['custom23']=='POPULATION'){
			$listenQueue = 'ag_pension_population_pull';
		}else if($ticket['custom23']=='WDD'){
			$listenQueue = 'ag_pension_wdd_pull';
		}else if($ticket['custom23']=='YASAT'){
			$listenQueue = 'ag_pension_yasat_pull';
		}else if($ticket['custom23']=='ENERGY'){
			$listenQueue = 'ag_pension_energy_pull';
		}else if($ticket['custom23']=='FWF'){
			$listenQueue = 'ag_pension_fwf_pull';
		}else if($ticket['custom23']=='CMIT'){
			$listenQueue = 'ag_pension_cmit_pull';
		}else if($ticket['custom23']=='FINANCE'){
			$listenQueue = 'ag_pension_finance_pull';
		}else if($ticket['custom23']=='FOOD'){
			$listenQueue = 'ag_pension_food_pull';
		}else if($ticket['custom23']=='AGRI'){
			$listenQueue = 'ag_pension_agri_pull';
		}else if($ticket['custom23']=='HOME'){
			$listenQueue = 'ag_pension_home_pull';
		}else if($ticket['custom23']=='HUDPHE'){
			$listenQueue = 'ag_pension_hudphe_pull';
		}else if($ticket['custom23']=='ENP'){
			$listenQueue = 'ag_pension_enp_pull';
		}else if($ticket['custom23']=='PROSECUTION'){
			$listenQueue = 'ag_pension_prosecution_pull';
		}

		else{
			$listenQueue    = 'sed_pension_teachers';
		}
		
		//$listenQueue    = 'sed_pension_teachers_staging2';
		$listenTag      = 'normal';
		$permanent      = true;
		$pusher->push($listenQueue, json_encode($pushData), true);
		
		//hesk_dbQuery("UPDATE `hesk_ag_penrabbitmq` SET `status`='{$status}' , `dt` = '".$datee."' WHERE `ticket_id`='".$ticket['id']."'");
			
	}
}
elseif ($status != 0)
{
    $status_name = hesk_get_status_name($status);
	$action = sprintf($hesklang['tsst'], $status_name);
    $revision = sprintf($hesklang['thist9'],hesk_date(),addslashes($status_name),addslashes($_SESSION['name']).' ('.$_SESSION['user'].')');

	// Ticket is not resolved
	$closedby_sql = ' , `closedat`=NULL, `closedby`=NULL ';

	$result = hesk_dbQuery("SELECT * FROM `".hesk_dbEscape($hesk_settings['db_pfix'])."tickets` WHERE `trackid`='".hesk_dbEscape($trackingID)."' LIMIT 1");
	if (hesk_dbNumRows($result) != 1)
	{
		hesk_error($hesklang['ticket_not_found']);
	}
	$ticket = hesk_dbFetchAssoc($result);
	
	
	if($status == 6){
		 //echo __LINE__	; exit;
		if($ticket['officer_id'] > 0){
			
			$getMessage = hesk_dbQuery("SELECT * FROM `".hesk_dbEscape($hesk_settings['db_pfix'])."notes` WHERE `ticket`='".hesk_dbEscape($ticket['id'])."' ORDER BY id DESC LIMIT 1");
			$msg = "";
			if (hesk_dbNumRows($getMessage) != 1)
			{
				hesk_error("Notes not found.");
			}
			$msg = hesk_dbFetchAssoc($getMessage);
			$pushData['officer_id'] = $ticket['officer_id'];
			$pushData['retirement_id'] = $ticket['retirement_id'];
			$pushData['cnic'] = $ticket['custom3'];
			$pushData['message'] = $msg['message'];
			$pushData['status_date'] = date('Y-m-d h:i:s',strtotime($msg['dt']));
			$pushData['request_status'] = "Approved";
			$pushData['department'] = $ticket['custom23'];
			//print_r($pushData);exit;
			//$pushData1['test'] = 'This is testing message.';
			//pushData(json_encode($pushData));
			
			$pusher       = new Rabbitmq_client();

			if($ticket['custom23']=='SNGAD'){
				$listenQueue    = 'ag_pension_sngad_pull';
			}else if($ticket['custom23']=='BOR'){
				$listenQueue    = 'ag_pension_bor_pull';
			}else if($ticket['custom23']=='CNW'){
				$listenQueue    = 'ag_pension_cnw_pull';
			}else if($ticket['custom23']=='COOPERATIVES'){
				$listenQueue    = 'ag_pension_cooperative_pull';
			}else if($ticket['custom23']=='MPDD'){
				$listenQueue    = 'ag_pension_mpdd_pull';
			}else if($ticket['custom23']=='PND'){
				$listenQueue    = 'ag_pension_pnd_pull';
			}
			else if($ticket['custom23']=='IRRIGATION'){
				$listenQueue    = 'ag_pension_irrigation_pull';
			}else if($ticket['custom23']=='SWD'){
				$listenQueue    = 'ag_pension_swd_pull';
			}else if($ticket['custom23']=='GS'){
				$listenQueue    = 'ag_pension_gs_pull';
			}else if($ticket['custom23']=='LNPF'){
				$listenQueue    = 'ag_pension_lnpf_pull';
			}else if($ticket['custom23']=='LIVESTOCK'){
				$listenQueue    = 'ag_pension_livestock_pull';
			}else if($ticket['custom23']=='TRANSPORT'){
				$listenQueue    = 'ag_pension_transport_pull';
			}else if($ticket['custom23']=='INC'){
				$listenQueue    = 'ag_pension_inc_pull';
			}else if($ticket['custom23']=='EXCISE'){
				$listenQueue    = 'ag_pension_excise_pull';
			}else if($ticket['custom23']=='HRMA'){
				$listenQueue    = 'ag_pension_hrma_pull';
			}else if($ticket['custom23']=='MNM'){
				$listenQueue    = 'ag_pension_mnm_pull';
			}else if($ticket['custom23']=='ACE'){
				$listenQueue    = 'ag_pension_ace_pull';
			}else if($ticket['custom23']=='AUQAF'){
				$listenQueue    = 'ag_pension_auqaf_pull';
			}else if($ticket['custom23']=='ZAKAT'){
				$listenQueue    = 'ag_pension_zakat_pull';
			}else if($ticket['custom23']=='LITERACY'){
				$listenQueue    = 'ag_pension_literacy_pull';
			}else if($ticket['custom23']=='HED'){
				$listenQueue    = 'ag_pension_hed_pull';
			}

			else if($ticket['custom23']=='ICI'){
				$listenQueue = 'ag_pension_ici_pull';
			}else if($ticket['custom23']=='LABOUR'){
				$listenQueue = 'ag_pension_labour_pull';
			}else if($ticket['custom23']=='LGCD'){
				$listenQueue = 'ag_pension_lgcd_pull';
			}else if($ticket['custom23']=='SPECIALEDU'){
				$listenQueue = 'ag_pension_specialedu_pull';
			}else if($ticket['custom23']=='TOURISM'){
				$listenQueue = 'ag_pension_tourism_pull';
			}else if($ticket['custom23']=='POPULATION'){
				$listenQueue = 'ag_pension_population_pull';
			}else if($ticket['custom23']=='WDD'){
				$listenQueue = 'ag_pension_wdd_pull';
			}else if($ticket['custom23']=='YASAT'){
				$listenQueue = 'ag_pension_yasat_pull';
			}else if($ticket['custom23']=='ENERGY'){
				$listenQueue = 'ag_pension_energy_pull';
			}else if($ticket['custom23']=='FWF'){
				$listenQueue = 'ag_pension_fwf_pull';
			}else if($ticket['custom23']=='CMIT'){
				$listenQueue = 'ag_pension_cmit_pull';
			}else if($ticket['custom23']=='FINANCE'){
				$listenQueue = 'ag_pension_finance_pull';
			}else if($ticket['custom23']=='FOOD'){
				$listenQueue = 'ag_pension_food_pull';
			}else if($ticket['custom23']=='AGRI'){
				$listenQueue = 'ag_pension_agri_pull';
			}else if($ticket['custom23']=='HOME'){
				$listenQueue = 'ag_pension_home_pull';
			}else if($ticket['custom23']=='HUDPHE'){
				$listenQueue = 'ag_pension_hudphe_pull';
			}else if($ticket['custom23']=='ENP'){
				$listenQueue = 'ag_pension_enp_pull';
			}else if($ticket['custom23']=='PROSECUTION'){
				$listenQueue = 'ag_pension_prosecution_pull';
			}

			else{
				$listenQueue    = 'sed_pension_teachers';
			}

			//$listenQueue    = 'sed_pension_teachers_staging';
			$listenTag      = 'normal';
			$permanent      = true;
			$pusher->push($listenQueue, json_encode($pushData), true);

			hesk_dbQuery("UPDATE `hesk_ag_penrabbitmq` SET `status`='{$status}' WHERE `ticket_id`='".$ticket['id']."'");
		}
	}
	
	if ($status == 7) {//Case Returned
		//echo __LINE__	; exit;
		if($ticket['officer_id'] > 0){
			$getMessage = hesk_dbQuery("SELECT * FROM `".hesk_dbEscape($hesk_settings['db_pfix'])."notes` WHERE `ticket`='".hesk_dbEscape($ticket['id'])."' ORDER BY id DESC LIMIT 1");
			$msg = "";
			if (hesk_dbNumRows($getMessage) != 1)
			{
				hesk_error("Notes not found.");
			}
			$msg = hesk_dbFetchAssoc($getMessage);
			$pushData['officer_id'] = $ticket['officer_id'];
			$pushData['retirement_id'] = $ticket['retirement_id'];
			$pushData['cnic'] = $ticket['custom3'];
			$pushData['message'] = $msg['message'];
			$pushData['status_date'] = date('Y-m-d h:i:s',strtotime($msg['dt']));
			$pushData['request_status'] = "Case Returned";
			$pushData['department'] = $ticket['custom23'];
			//pushData(json_encode($pushData));
			$pusher       = new Rabbitmq_client();
			if($ticket['custom23']=='SNGAD'){
				$listenQueue    = 'ag_pension_sngad_pull';
			}else if($ticket['custom23']=='BOR'){
				$listenQueue    = 'ag_pension_bor_pull';
			}else if($ticket['custom23']=='CNW'){
				$listenQueue    = 'ag_pension_cnw_pull';
			}else if($ticket['custom23']=='COOPERATIVES'){
				$listenQueue    = 'ag_pension_cooperative_pull';
			}else if($ticket['custom23']=='MPDD'){
				$listenQueue    = 'ag_pension_mpdd_pull';
			}else if($ticket['custom23']=='PND'){
				$listenQueue    = 'ag_pension_pnd_pull';
			}
			else if($ticket['custom23']=='IRRIGATION'){
				$listenQueue    = 'ag_pension_irrigation_pull';
			}else if($ticket['custom23']=='SWD'){
				$listenQueue    = 'ag_pension_swd_pull';
			}else if($ticket['custom23']=='GS'){
				$listenQueue    = 'ag_pension_gs_pull';
			}else if($ticket['custom23']=='LNPF'){
				$listenQueue    = 'ag_pension_lnpf_pull';
			}else if($ticket['custom23']=='LIVESTOCK'){
				$listenQueue    = 'ag_pension_livestock_pull';
			}else if($ticket['custom23']=='TRANSPORT'){
				$listenQueue    = 'ag_pension_transport_pull';
			}else if($ticket['custom23']=='INC'){
				$listenQueue    = 'ag_pension_inc_pull';
			}else if($ticket['custom23']=='EXCISE'){
				$listenQueue    = 'ag_pension_excise_pull';
			}else if($ticket['custom23']=='HRMA'){
				$listenQueue    = 'ag_pension_hrma_pull';
			}else if($ticket['custom23']=='MNM'){
				$listenQueue    = 'ag_pension_mnm_pull';
			}else if($ticket['custom23']=='ACE'){
				$listenQueue    = 'ag_pension_ace_pull';
			}else if($ticket['custom23']=='AUQAF'){
				$listenQueue    = 'ag_pension_auqaf_pull';
			}else if($ticket['custom23']=='ZAKAT'){
				$listenQueue    = 'ag_pension_zakat_pull';
			}else if($ticket['custom23']=='LITERACY'){
				$listenQueue    = 'ag_pension_literacy_pull';
			}else if($ticket['custom23']=='HED'){
				$listenQueue    = 'ag_pension_hed_pull';
			}

			else if($ticket['custom23']=='ICI'){
				$listenQueue = 'ag_pension_ici_pull';
			}else if($ticket['custom23']=='LABOUR'){
				$listenQueue = 'ag_pension_labour_pull';
			}else if($ticket['custom23']=='LGCD'){
				$listenQueue = 'ag_pension_lgcd_pull';
			}else if($ticket['custom23']=='SPECIALEDU'){
				$listenQueue = 'ag_pension_specialedu_pull';
			}else if($ticket['custom23']=='TOURISM'){
				$listenQueue = 'ag_pension_tourism_pull';
			}else if($ticket['custom23']=='POPULATION'){
				$listenQueue = 'ag_pension_population_pull';
			}else if($ticket['custom23']=='WDD'){
				$listenQueue = 'ag_pension_wdd_pull';
			}else if($ticket['custom23']=='YASAT'){
				$listenQueue = 'ag_pension_yasat_pull';
			}else if($ticket['custom23']=='ENERGY'){
				$listenQueue = 'ag_pension_energy_pull';
			}else if($ticket['custom23']=='FWF'){
				$listenQueue = 'ag_pension_fwf_pull';
			}else if($ticket['custom23']=='CMIT'){
				$listenQueue = 'ag_pension_cmit_pull';
			}else if($ticket['custom23']=='FINANCE'){
				$listenQueue = 'ag_pension_finance_pull';
			}else if($ticket['custom23']=='FOOD'){
				$listenQueue = 'ag_pension_food_pull';
			}else if($ticket['custom23']=='AGRI'){
				$listenQueue = 'ag_pension_agri_pull';
			}else if($ticket['custom23']=='HOME'){
				$listenQueue = 'ag_pension_home_pull';
			}else if($ticket['custom23']=='HUDPHE'){
				$listenQueue = 'ag_pension_hudphe_pull';
			}else if($ticket['custom23']=='ENP'){
				$listenQueue = 'ag_pension_enp_pull';
			}else if($ticket['custom23']=='PROSECUTION'){
				$listenQueue = 'ag_pension_prosecution_pull';
			}


			else{
				$listenQueue    = 'sed_pension_teachers';
			}
			//$listenQueue    = 'sed_pension_teachers_staging';
			$listenTag      = 'normal';
			$permanent      = true;
			$pusher->push($listenQueue, json_encode($pushData), true);

			hesk_dbQuery("UPDATE `hesk_ag_penrabbitmq` SET `status`='{$status}' WHERE `ticket_id`='".$ticket['id']."'");
		}
	}
}
else // Opened
{
	$action = $hesklang['ticket_been'] . ' ' . $hesklang['opened'];
    $revision = sprintf($hesklang['thist4'],hesk_date(),addslashes($_SESSION['name']).' ('.$_SESSION['user'].')');

	// Ticket is not resolved
	$closedby_sql = ' , `closedat`=NULL, `closedby`=NULL ';
}

hesk_dbQuery("UPDATE `".hesk_dbEscape($hesk_settings['db_pfix'])."tickets` SET `status`='{$status}', `locked`='{$locked}' $closedby_sql , `history`=CONCAT(`history`,'".hesk_dbEscape($revision)."') WHERE `trackid`='".hesk_dbEscape($trackingID)."'");

if (hesk_dbAffectedRows() != 1)
{
	hesk_error("$hesklang[int_error]: $hesklang[trackID_not_found].");
}

hesk_process_messages($action,'admin_ticket.php?track='.$trackingID.'&Refresh='.rand(10000,99999),'SUCCESS');
//hesk_process_messages($action,'admin_ticket.php?track='.$trackingID.'&Refresh=80063','SUCCESS');
