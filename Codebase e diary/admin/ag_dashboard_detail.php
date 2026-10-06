<?php

define('IN_SCRIPT', 1);
define('HESK_PATH', '../');

/* Get all the required files and functions */
require(HESK_PATH . 'hesk_settings.inc.php');
require(HESK_PATH . 'inc/common.inc.php');
require(HESK_PATH . 'inc/admin_functions.inc.php');
hesk_load_database_functions();

hesk_session_start();
hesk_dbConnect();
hesk_isLoggedIn();

define('CALENDAR', 1);
define('MAIN_PAGE', 1);
define('AUTO_RELOAD', 1);

/* Print header */
require_once(HESK_PATH . 'inc/header.inc.php');

$href = 'admin_main.php';
/* Print admin navigation */
require_once(HESK_PATH . 'inc/show_admin_nav.inc.php');
// Load custom fields
require_once(HESK_PATH . 'inc/custom_fields.inc.php');

// Load statuses
require_once(HESK_PATH . 'inc/statuses.inc.php');

//MySQL QUERY
if($_GET['datefrom']!=''){
    $date_from = " AND created_at>='".$_GET['datefrom']."'";
}else{
    $date_from='';
}
if($_GET['dateto']!=''){
    $date_to = " AND created_at<='".$_GET['dateto']."'";
}else{
    $date_to='';
}

if($_GET['department']!=''){
    $department=$_GET['department'];
    $where_department=" AND department= '".$department."' ";	
}else{
    $department='';	
    $where_department='';	
}

if($_GET['status']=='0'){
    $heading = '<h3>Recieved Cases</h3>';
    $get_query = hesk_dbQuery("SELECT * FROM `".hesk_dbEscape($hesk_settings['db_pfix'])."rabbitmq` WHERE status IN(1,4,6,7) $date_from $date_to $where_department ");
}else if($_GET['status']=='3'){
    $heading = '<h3>In-Process Cases</h3>';
    $get_query = hesk_dbQuery("SELECT * FROM `".hesk_dbEscape($hesk_settings['db_pfix'])."rabbitmq` WHERE status IN(1,4) $date_from $date_to $where_department ");
}else if($_GET['status']=='1'){
    $heading = '<h3>Approved Cases</h3>';
    $get_query = hesk_dbQuery("SELECT * FROM `".hesk_dbEscape($hesk_settings['db_pfix'])."rabbitmq` WHERE status=6 $date_from $date_to $where_department ");
}else if($_GET['status']=='2'){
    $heading = '<h3>Rejected Cases</h3>';
    $get_query = hesk_dbQuery("SELECT * FROM `".hesk_dbEscape($hesk_settings['db_pfix'])."rabbitmq` WHERE status=7 $date_from $date_to $where_department ");
}else if($_GET['status']=='4'){
    $heading = '<h3>Last 1-3 days In-Process Cases</h3>';
    $get_query = hesk_dbQuery("SELECT * FROM `".hesk_dbEscape($hesk_settings['db_pfix'])."rabbitmq` WHERE status IN(1,4) AND DATE(created_at) BETWEEN DATE_SUB(CURDATE(), INTERVAL 3 DAY) AND DATE_SUB(CURDATE(), INTERVAL 1 DAY) $where_department");
}else if($_GET['status']=='5'){
    $heading = '<h3>Last 3-6 days In-Process Cases</h3>';
    $get_query = hesk_dbQuery("SELECT * FROM `".hesk_dbEscape($hesk_settings['db_pfix'])."rabbitmq` WHERE status IN(1,4) AND DATE(created_at) BETWEEN DATE_SUB(CURDATE(), INTERVAL 6 DAY) AND DATE_SUB(CURDATE(), INTERVAL 4 DAY) $where_department");
}else if($_GET['status']=='6'){
    $heading = '<h3>Last 6-9 days In-Process Cases</h3>';
    $get_query = hesk_dbQuery("SELECT * FROM `".hesk_dbEscape($hesk_settings['db_pfix'])."rabbitmq` 
    WHERE status IN(1,4) 
    AND DATE(created_at) BETWEEN DATE_SUB(CURDATE(), INTERVAL 9 DAY) AND DATE_SUB(CURDATE(), INTERVAL 7 DAY) $where_department");
}else if($_GET['status']=='7'){
    $heading = '<h3>More Than Last 10 days In-Process Cases</h3>';
    $get_query = hesk_dbQuery("SELECT * FROM `".hesk_dbEscape($hesk_settings['db_pfix'])."rabbitmq` 
    WHERE status IN(1,4) 
    AND DATE(created_at) <= DATE_SUB(CURDATE(), INTERVAL 10 DAY) $where_department");
}else if($_GET['status']=='8'){
    $heading = '<h3>Last 1-3 days Approved Cases</h3>';
    $get_query = hesk_dbQuery("SELECT * FROM `".hesk_dbEscape($hesk_settings['db_pfix'])."rabbitmq` 
    WHERE status=6
    AND DATE(created_at) BETWEEN DATE_SUB(CURDATE(), INTERVAL 3 DAY) AND DATE_SUB(CURDATE(), INTERVAL 1 DAY) $where_department");
}else if($_GET['status']=='9'){
    $heading = '<h3>Last 3-6 days Approved Cases</h3>';
    $get_query = hesk_dbQuery("SELECT * FROM `".hesk_dbEscape($hesk_settings['db_pfix'])."rabbitmq` 
    WHERE status=6
    AND DATE(created_at) BETWEEN DATE_SUB(CURDATE(), INTERVAL 6 DAY) AND DATE_SUB(CURDATE(), INTERVAL 4 DAY) $where_department");
}else if($_GET['status']=='10'){
    $heading = '<h3>Last 6-9 days Approved Cases</h3>';
    $get_query = hesk_dbQuery("SELECT * FROM `".hesk_dbEscape($hesk_settings['db_pfix'])."rabbitmq` 
    WHERE status=6
    AND DATE(created_at) BETWEEN DATE_SUB(CURDATE(), INTERVAL 9 DAY) AND DATE_SUB(CURDATE(), INTERVAL 7 DAY) $where_department");
}else if($_GET['status']=='11'){
    $heading = '<h3>More Than Last 10 days Approved Cases</h3>';
    $get_query = hesk_dbQuery("SELECT * FROM `".hesk_dbEscape($hesk_settings['db_pfix'])."rabbitmq` 
    WHERE status=6
    AND DATE(created_at) <= DATE_SUB(CURDATE(), INTERVAL 10 DAY) $where_department");
}else if($_GET['status']=='12'){
    $heading = '<h3>In-Process Applications Department Wise</h3>';
    $get_query = hesk_dbQuery("SELECT * FROM `".hesk_dbEscape($hesk_settings['db_pfix'])."rabbitmq` 
    WHERE status IN(1,4)
     $where_department");
}else if($_GET['status']=='13'){
    $heading = '<h3>Approved Applications Department Wise</h3>';
    $get_query = hesk_dbQuery("SELECT * FROM `".hesk_dbEscape($hesk_settings['db_pfix'])."rabbitmq` 
    WHERE status=6
    $where_department");
}else if($_GET['status']=='14'){
    $heading = '<h3>Return Applications Department Wise</h3>';
    $get_query = hesk_dbQuery("SELECT * FROM `".hesk_dbEscape($hesk_settings['db_pfix'])."rabbitmq` 
    WHERE status=7
    $where_department");
}



?>

<link rel="stylesheet" media="all" href="https://cdn.datatables.net/1.11.3/css/jquery.dataTables.min.css">
<script src='https://cdn.datatables.net/1.11.3/js/jquery.dataTables.min.js'></script>
<div class="table-wrap">
    <?php echo $heading; ?>
    <table class="table sindu-table ticket-list sindu_origin_table" id="sync_tickets">
        <thead>
            <tr>
                <th>#</th>
                <th>Officer ID</th>
                <th>Retirement ID</th>
                <th>CNIC</th>
                <th>Name</th>
                <th>Personal #</th>
                <th>Contact</th>
                <th>Department</th>
                <th>Status</th>
                <!-- <th>Action</th> -->
            </tr>
        </thead>
        <tbody>
            
            <?php
            $count=1;
            while ($row = hesk_dbFetchAssoc($get_query)){ ?> 
                
            <tr>
                <td><?=$count?></td>
                <td><?=$row['officer_id']?></td>
                <td><?=$row['retirement_id']?></td>
                <td><?=$row['cnic']?></td>
                <td><?=$row['firstname']?></td>
                <td><?=$row['personal_no']?></td>
                <td><?=$row['opr_phone']?></td>
                <td><?=$row['department']?></td>   
                <td><span class="replied"><?php 
                if($row['status']==1 || $row['status']==4){ 
                    echo 'Pending'; 
                }else if($row['status']==6){
                    echo 'Case Approved'; 
                }else if($row['status']==7){
                    echo 'Case Return'; 
                } ?></span></td>
            </tr>
                
            <?php $count++; } ?>

        </tbody>
    </table>
</div>
<script>
    $(document).ready(function () {
        $('#sync_tickets').DataTable();
    });
</script>

<?php
/* Clean unneeded session variables */
hesk_cleanSessionVars('hide');
?>
<link rel="stylesheet" href="<?php echo HESK_PATH; ?>css/bootstrap.min.css">
<?php require_once(HESK_PATH . 'inc/footer.inc.php');
exit();
?>
