<?php

define('IN_SCRIPT', 1);
define('HESK_PATH', '../');
require_once('Rabbitmq.php');
require(HESK_PATH . 'hesk_settings.inc.php');
require(HESK_PATH . 'inc/common.inc.php');
require_once('database.php');

hesk_load_database_functions();
hesk_dbConnect();
try{
    $listener = new Rabbitmq_client();
}catch(Exception $e){
    
    if(strpos("stream_socket_client(): unable to connect to tcp://10.50.125.79:5672 (Connection timed out)", 'unable') !== false){
        echo "Error: Queue connection failed. Please contact to system administrator. <br/>
        Original Message: " . $e->getMessage();
    }else{
        echo $e->getMessage();
    }
}
$listenQueue = 'ag_pension_teachers';
$listenTag = 'normal';
$permanent = true;

function createDirectory($key=null,$img=null){
   if (!file_exists("../ticket_images") && !is_dir("../ticket_images")) {
      mkdir("../ticket_images",0777,true);
      chmod("../ticket_images", 0755);      
   }
   if (!file_exists("../ticket_images/$key") && !is_dir("../ticket_images/$key")) {
      mkdir("../ticket_images/$key",0777,true);
      chmod("../ticket_images/$key", 0755);        
   }
   if (!file_exists("../ticket_images/$key/$img[3]") && !is_dir("../ticket_images/$key/$img[3]")) {
      mkdir("../ticket_images/$key/$img[3]",0777,true);
      chmod("../ticket_images/$key/$img[3]", 0755);      
   }
   if (!file_exists("../ticket_images/$key/$img[3]/$img[4]") && !is_dir("../ticket_images/$key/$img[3]/$img[4]")) {
      mkdir("../ticket_images/$key/$img[3]/$img[4]",0777,true);
      chmod("../ticket_images/$key/$img[3]/$img[4]", 0755);      
   }

}

function createHistoryDirectory($ticket_id,$key=null,$img=null){
    if (!file_exists("../ticket_images_history") && !is_dir("../ticket_images_history")) {
       mkdir("../ticket_images_history",0777,true);
       chmod("../ticket_images_history", 0777);      
    }
    if (!file_exists("../ticket_images_history/$ticket_id") && !is_dir("../ticket_images_history/$ticket_id")) {
       mkdir("../ticket_images_history/$ticket_id",0777,true);
       chmod("../ticket_images_history/$ticket_id", 0777);
    }
    if (!file_exists("../ticket_images_history/$ticket_id/$key") && !is_dir("../ticket_images_history/$ticket_id/$key")) {
       mkdir("../ticket_images_history/$ticket_id/$key",0777,true);
       chmod("../ticket_images_history/$ticket_id/$key", 0777);        
    }
    if (!file_exists("../ticket_images_history/$ticket_id/$key/$img[3]") && !is_dir("../ticket_images_history/$ticket_id/$key/$img[3]")) {
       mkdir("../ticket_images_history/$ticket_id/$key/$img[3]",0777,true);
       chmod("../ticket_images_history/$ticket_id/$key/$img[3]", 0777);      
    }
    if (!file_exists("../ticket_images_history/$ticket_id/$key/$img[3]/$img[4]") && !is_dir("../ticket_images_history/$ticket_id/$key/$img[3]/$img[4]")) {
       mkdir("../ticket_images_history/$ticket_id/$key/$img[3]/$img[4]",0777,true);
       chmod("../ticket_images_history/$ticket_id/$key/$img[3]/$img[4]", 0777);      
    }

    

   
}

function createTmpDirectory($key=null,$img=null){
    if (!file_exists("../tmp") && !is_dir("../tmp")) {
       mkdir("../tmp",0777,true);
       chmod("../tmp", 0777);      
    }
    if (!file_exists("../tmp/$key") && !is_dir("../tmp/$key")) {
       mkdir("../tmp/$key",0777,true);
       chmod("../tmp/$key", 0777);        
    }
    if (!file_exists("../tmp/$key/$img[3]") && !is_dir("../tmp/$key/$img[3]")) {
       mkdir("../tmp/$key/$img[3]",0777,true);
       chmod("../tmp/$key/$img[3]", 0777);      
    }
    if (!file_exists("../tmp/$key/$img[3]/$img[4]") && !is_dir("../tmp/$key/$img[3]/$img[4]")) {
       mkdir("../tmp/$key/$img[3]/$img[4]",0777,true);
       chmod("../tmp/$key/$img[3]/$img[4]", 0777);      
    }
 
}

function get_old_images($ticket_id){
    $qres = hesk_dbQuery("SELECT * FROM `".hesk_dbEscape($hesk_settings['db_pfix'])."hesk_ticket_images` WHERE `ticket_id`='{$ticket_id}' LIMIT 1");
    return $res = hesk_dbFetchAssoc($qres);
}

 function moveFileToDirectory($url=null,$key=null,$img=null,$ticket_id=null){
    $directory = (is_null($ticket_id) ? "../ticket_images" : "../ticket_images");
    //Save images into directories
    $getFile = $url;
    $path = "$directory/$key/$img[3]/$img[4]/$img[5]";
    $fp = fopen($path, 'w');
    $ch = curl_init($getFile);
    curl_setopt($ch, CURLOPT_FILE, $fp);
    curl_setopt($ch, CURLOPT_RETURNTRANSFER, 1);
    curl_setopt($ch, CURLOPT_FOLLOWLOCATION, 1);
    curl_setopt($ch, CURLOPT_COOKIEJAR, 'cookies');
    curl_setopt($ch, CURLOPT_COOKIEFILE, 'cookies');
    $data = curl_exec($ch);
    fwrite($fp,$data);
    curl_close($ch);
    fclose($fp);  
    return true;
}

function getImage($key=null,$val=null,$officer_id=null,$retirement_id=null){

      if(!empty($val)){
        foreach($val as $k=>$v){
            $img = explode('/',$v);
            
            $qres = hesk_dbQuery("SELECT * FROM `".hesk_dbEscape($hesk_settings['db_pfix'])."hesk_ticket_images` WHERE `officer_id`='{$officer_id}' and `penrabbit_id_fk` = 0 LIMIT 1");
            $res = hesk_dbFetchAssoc($qres);

            createDirectory($key,$img);

            if(empty($res)){
                //add new user here
                $date = date("Y-m-d H:i:s");
                hesk_dbQuery("INSERT INTO ".hesk_dbEscape($hesk_settings['db_pfix'])."`hesk_ticket_images`
                                (officer_id,retirement_id,$key,`status`,created_at)
                                VALUES 
                                (" . hesk_dbEscape($officer_id) . ",
                                " . hesk_dbEscape($retirement_id) . ",
                                    '$img[5]',
                                ".  hesk_dbEscape(1) . ",
                                    '$date'
                )");
                
                moveFileToDirectory($v,$key,$img);

            }
                // else if(strpos($res[$key],$img[5]) === FALSE){
            else{
               //update record here
               if($res[$key] != '' ){
                  $new_val = "CONCAT($key,$img[5])";
                  hesk_dbQuery("UPDATE `".hesk_dbEscape($hesk_settings['db_pfix'])."hesk_ticket_images` SET $key = CONCAT($key,',".$img[5]."') WHERE `officer_id`=".hesk_dbEscape($officer_id)." and `penrabbit_id_fk` = 0 ");
                  //createDirectory($key,$img);
                  moveFileToDirectory($v,$key,$img,$get_duplicate_data['ticket_id']);
               }else{
                  hesk_dbQuery("UPDATE `".hesk_dbEscape($hesk_settings['db_pfix'])."hesk_ticket_images` SET $key = '$img[5]' WHERE `officer_id`=".hesk_dbEscape($officer_id)." and `penrabbit_id_fk` = 0");
                  //createDirectory($key,$img);
                  moveFileToDirectory($v,$key,$img,$get_duplicate_data['ticket_id']);
               }
            }
        }
        return true;
      }else{
         return false;
      }  
}

function processImagesFromQue($data){
   foreach($data as $key => $val){
  
      if($key == 'officer_id'){
         $officer_id = $val;
      }
      if($key == 'retirement_id'){
         $retirement_id = $val;
      }    
       switch ($key) {
           case "annex_a":
            getImage($key,$val,$officer_id,$retirement_id);
           break;
           case "annex_b":
            getImage($key,$val,$officer_id,$retirement_id);
           break;
           case "service_statement":
            getImage($key,$val,$officer_id,$retirement_id);
           break;
           case "no_demand_certificate_building":
            getImage($key,$val,$officer_id,$retirement_id);
           break;           
           case "affidavit":
            getImage($key,$val,$officer_id,$retirement_id);
           break;           
           case "service_book":
            getImage($key,$val,$officer_id,$retirement_id);
           break;   
           case "forwarding_letter_ddo":
            getImage($key,$val,$officer_id,$retirement_id);
           break;           
           case "attested_cnic_ddo":
            getImage($key,$val,$officer_id,$retirement_id);
           break;           
           case "passport_size_photos":
            getImage($key,$val,$officer_id,$retirement_id);
           break;   
           case "pension_sanctioned_form":
            getImage($key,$val,$officer_id,$retirement_id);
           break;           
           case "familymember_verified_psa":
            getImage($key,$val,$officer_id,$retirement_id);
           break;           
           case "frc_familyregistration":
               getImage($key,$val,$officer_id,$retirement_id);
           break;
           case "last_paymentcertificate":
               getImage($key,$val,$officer_id,$retirement_id);
           break;
           case "bank_optionform":
               getImage($key,$val,$officer_id,$retirement_id);
           break;
           case "indemnity_bond":
               getImage($key,$val,$officer_id,$retirement_id);
           break;
           case "last_computirzedpayslip":
               getImage($key,$val,$officer_id,$retirement_id);
           break;
           case "retirment_letter":
               getImage($key,$val,$officer_id,$retirement_id);
           break;
           case "medical_certificate":
               getImage($key,$val,$officer_id,$retirement_id);
           break;
           case "nomarriage_certificate":
               getImage($key,$val,$officer_id,$retirement_id);
           break;
           case "lawful_widow_certificate":
               getImage($key,$val,$officer_id,$retirement_id);
           break;
           case "incomecertificate_signedbypsa":
               getImage($key,$val,$officer_id,$retirement_id);
           break;
           case "reason_for_latesubmission":
               getImage($key,$val,$officer_id,$retirement_id);
           break;
           case "computrized_deathcertificate":
               getImage($key,$val,$officer_id,$retirement_id);
           break;
           case "computrized_divorcecertification":
               getImage($key,$val,$officer_id,$retirement_id);
           break;
           case "computrized_divorcecertification":
               getImage($key,$val,$officer_id,$retirement_id);
           break;
           
       } 
    }
}

function check_duplicate($officer_id){
    $qres = hesk_dbQuery("SELECT * FROM `".hesk_dbEscape($hesk_settings['db_pfix'])."hesk_ticket_images` WHERE `officer_id`='{$officer_id}' and `penrabbit_id_fk` > 0 LIMIT 1");
    return $res = hesk_dbFetchAssoc($qres);
}

function check_duplicate_rabbit_user($officer_id){
    $qres = hesk_dbQuery("SELECT * FROM `".hesk_dbEscape($hesk_settings['db_pfix'])."hesk_ag_penrabbitmq` WHERE `officer_id`='{$officer_id}' and `ticket_id` = 0 LIMIT 1");
    return $res = hesk_dbFetchAssoc($qres);
}

$listener->pull($listenQueue, $permanent, $listenTag, function ($message) {
    try {
        $dinfo = $message->delivery_info;
        $pull_status = 'ACK';
        $pull_datetime = date('Y-m-d H:i:s');
        $listenQueue = 'FIRBKP';

        $res = json_decode($message->body,true);
        $tmp_res = $res;
        unset($tmp_res['officer_id']);
        unset($tmp_res['retirement_id']);
        unset($tmp_res['firstname']);
        unset($tmp_res['personal_no']);
        unset($tmp_res['cnic']);
        unset($tmp_res['opr_phone']);
       
        $check_rabbit_duplicate = check_duplicate_rabbit_user($res['officer_id']);
        $get_duplicate_data = check_duplicate($res['officer_id']);
		
        if(empty($check_rabbit_duplicate)){
            $ticket_id = $get_duplicate_data['ticket_id'];
            if($ticket_id > 0){
                foreach($tmp_res as $key => $vall){
                    if(!empty($vall)){
						//print_r($vall);exit;
						foreach($vall as $v){
							$img = explode('/',$v);
							createHistoryDirectory($ticket_id,$key,$img);
							$files = scandir("../ticket_images/$key/$img[3]/$img[4]/");
							$source_folder = "../ticket_images/$key/$img[3]/$img[4]/";    
							$destination_folder = "../ticket_images_history/$ticket_id/$key/$img[3]/$img[4]/";
							//print_r($files);
							foreach($files as $fname) {
								if($fname != '.' && $fname != '..') {
									rename($source_folder.$fname, $destination_folder.$fname);
									
								}
							} 
						}
						
                    }
                    
                }
            }
			 hesk_dbQuery("INSERT INTO `hesk_ag_penrabbitmq`
            (`listened_data`,`cnic`, `firstname`, `officer_id`, `opr_phone`, `personal_no`, `retirement_id`)
            VALUES 
            ('" . hesk_dbEscape($message->body) . "','" . hesk_dbEscape($res['cnic']) . "','" . hesk_dbEscape($res['firstname']) . "','" . hesk_dbEscape($res['officer_id']) . "','" . hesk_dbEscape($res['opr_phone']) . "','" . hesk_dbEscape($res['personal_no']) . "','" . hesk_dbEscape($res['retirement_id']) . "')");
            processImagesFromQue($res);
        }
        

        echo $message->body . ' ------------- ' . $message->delivery_info['exchange'] . ' -------- ' . $message->delivery_info['routing_key'] . '<br/>';
        $message->delivery_info['channel']->basic_ack($message->delivery_info['delivery_tag']);
        
    } catch (Exception $e) {
        $pull_status = 'NACK';
        $message->delivery_info['channel']->basic_nack($message->delivery_info['delivery_tag']);
    }
});
