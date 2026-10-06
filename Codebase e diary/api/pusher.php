<?php

require_once('Rabbitmq.php');
define('IN_SCRIPT', 1);
define('HESK_PATH', '../');

// require(HESK_PATH . 'hesk_settings.inc.php');
 //require(HESK_PATH . 'inc/common.inc.php');
require_once('database.php');
    


hesk_load_database_functions();
hesk_dbConnect();


function pushData($sample_data){
    $pusher       = new Rabbitmq_client();
    $listenQueue    = 'sed_pension_teachers';
    $listenTag      = 'normal';
    $permanent      = true;
    $pusher->push($listenQueue, $sample_data, true);
	return true;
     //echo '<pre>';
     //print_r($pusher);

}
//$pushData1['test'] = 'This is testing message.';
//pushData(json_encode($pushData1));
//echo __LINE__;

